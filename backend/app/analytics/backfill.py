"""Durable, bounded read-through history imports; never invoke paid Devin sessions.

Search discovers merged PR IDs; the PR endpoint supplies canonical merge/base data.
A checkpoint follows each read. Repeated reads after a crash are safe upserts.
"""

import calendar
import json
import time
import uuid
from datetime import date, timedelta

import httpx

from .metrics import covered


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


class MonthBackfill:
    def __init__(self, store, *, clock=time.time):
        self.store = store
        self.clock = clock
        self.pause_until = 0.0

    def request_selection(self, repository, *, end, days, baseline_end, stored_pulls=None):
        end = date.fromisoformat(end) if isinstance(end, str) else end
        baseline_end = (
            date.fromisoformat(baseline_end) if isinstance(baseline_end, str) else baseline_end
        )
        # Cover both rolling history and six calendar months, plus comparison.
        month_index = end.year * 12 + end.month - 1 - 6
        earliest = min(
            date(month_index // 12, month_index % 12 + 1, 1), end - timedelta(days=182 + days - 1)
        )
        ranges = [(earliest, end), (baseline_end - timedelta(days=days - 1), baseline_end)]
        requested = {}
        for start, stop in ranges:
            cursor = start.replace(day=1)
            while cursor <= stop:
                requested[cursor.isoformat()] = min(
                    month_end(cursor), max(stop, requested.get(cursor.isoformat(), cursor))
                )
                cursor = month_end(cursor) + timedelta(days=1)
        status = self.store.status(repository)
        # A verified empty month needs its own durable receipt. If a broad import
        # says complete but an entire month's records are absent, recheck GitHub.
        pulls = self.store.pulls(repository) if stored_pulls is None else stored_pulls
        populated_months = {
            pull["merged_at"][:7] + "-01" for pull in pulls if pull.get("merged_at")
        }
        now = self.clock()
        with self.store.connect() as db:
            db.lock()
            for month, through in requested.items():
                interval = {"start": month, "end": through.isoformat()}
                if covered({"months": status["months"]}, interval) or (
                    month in populated_months and covered(status, interval)
                ):
                    continue
                row = db.execute(
                    "SELECT * FROM analytics_months WHERE repository=:repo AND month=:month",
                    {"repo": repository, "month": month},
                ).fetchone()
                if row and row["requested_through"] >= through.isoformat():
                    continue
                progress = json.dumps(
                    {"ranges": [[month, through.isoformat()]], "page": 1, "pending": []}
                )
                db.execute(
                    "INSERT INTO analytics_months(repository,month,requested_through,state,progress,updated) "
                    "VALUES(:repo,:month,:through,'queued',:progress,:now) "
                    "ON CONFLICT(repository,month) DO UPDATE SET requested_through=:through,state='queued',"
                    "progress=:progress,attempts=0,next_retry=0,lease_token=NULL,lease_until=0,updated=:now",
                    {
                        "repo": repository,
                        "month": month,
                        "through": through.isoformat(),
                        "progress": progress,
                        "now": now,
                    },
                )
                self.store.bump(db, repository)
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT month,state,covered_through,requested_through,next_retry FROM analytics_months WHERE repository=:repo ORDER BY month",
                    {"repo": repository},
                )
                if row["month"] in requested
            ]
        pending = [row for row in rows if row["state"] != "ready"]
        return {
            "state": "attention"
            if any(row["state"] in ("blocked", "dead_letter") for row in pending)
            else "loading"
            if pending
            else "ready",
            "months": rows,
            "pending_months": len(pending),
        }

    def _claim(self):
        now = self.clock()
        token = uuid.uuid4().hex
        with self.store.connect() as db:
            db.lock()
            row = db.execute(
                "SELECT * FROM analytics_months WHERE state IN ('queued','retry','running') "
                "AND next_retry<=:now AND lease_until<=:now ORDER BY updated,month LIMIT 1",
                {"now": now},
            ).fetchone()
            if not row:
                return None
            row = dict(row)
            db.execute(
                "UPDATE analytics_months SET state='running',lease_token=:token,lease_until=:until "
                "WHERE repository=:repo AND month=:month",
                {
                    "token": token,
                    "until": now + 180,
                    "repo": row["repository"],
                    "month": row["month"],
                },
            )
            row["lease_token"] = token
            return row

    def _save(self, row, progress, *, state="running", delay=0, failed=False):
        now = self.clock()
        with self.store.connect() as db:
            result = db.execute(
                "UPDATE analytics_months SET progress=:progress,state=:state,updated=:now,"
                "lease_until=:lease,next_retry=:retry,attempts=:attempts,"
                "covered_through=CASE WHEN :state='ready' THEN requested_through ELSE covered_through END "
                "WHERE repository=:repo AND month=:month AND lease_token=:token",
                {
                    "progress": json.dumps(progress),
                    "state": state,
                    "now": now,
                    "lease": now + 180 if state == "running" else 0,
                    "retry": now + delay,
                    "attempts": row["attempts"] + 1 if failed else 0,
                    "repo": row["repository"],
                    "month": row["month"],
                    "token": row["lease_token"],
                },
            )
            if result.rowcount:
                self.store.bump(db, row["repository"])
            return bool(result.rowcount)

    def run_once(self, client, *, max_requests=10):
        if self.clock() < self.pause_until:
            return False
        row = self._claim()
        if row is None:
            return False
        progress = json.loads(row["progress"])
        try:
            for _ in range(max_requests):
                if progress["pending"]:
                    number = progress["pending"][0]
                    response = client.get(
                        f"https://api.github.com/repos/{row['repository']}/pulls/{number}"
                    )
                    response.raise_for_status()
                    pull = response.json()
                    if pull.get("number") != number or not pull.get("merged_at"):
                        raise ValueError("Search result no longer describes a merged PR")
                    merged_day = date.fromisoformat(pull["merged_at"][:10]).isoformat()
                    if not row["month"] <= merged_day <= row["requested_through"]:
                        raise ValueError("Merged PR falls outside requested month")
                    if not self.store.upsert(
                        row["repository"],
                        [pull],
                        month_claim=(row["month"], row["lease_token"], self.clock()),
                    ):
                        return False
                    progress["pending"].pop(0)
                elif not progress["ranges"]:
                    self._save(row, progress, state="ready")
                    return True
                else:
                    start, end = progress["ranges"][0]
                    response = client.get(
                        "https://api.github.com/search/issues",
                        params={
                            "q": f"repo:{row['repository']} is:pr is:merged merged:{start}..{end}",
                            "sort": "created",
                            "order": "asc",
                            "per_page": 100,
                            "page": progress["page"],
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    if data.get("incomplete_results") is not False or not isinstance(
                        data.get("items"), list
                    ):
                        raise ValueError("GitHub returned incomplete search results")
                    total = data["total_count"]
                    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                        raise ValueError("Invalid GitHub result count")
                    if total <= 1000 and len(data["items"]) != min(
                        100, max(0, total - (progress["page"] - 1) * 100)
                    ):
                        raise ValueError("GitHub search pagination is incomplete")
                    if total > 1000:
                        first, last = date.fromisoformat(start), date.fromisoformat(end)
                        if first == last:
                            raise OverflowError("GitHub daily search exceeds 1000 results")
                        middle = first + (last - first) // 2
                        progress["ranges"][0:1] = [
                            [start, middle.isoformat()],
                            [(middle + timedelta(days=1)).isoformat(), end],
                        ]
                        progress["page"] = 1
                    else:
                        numbers = [item["number"] for item in data["items"]]
                        seen = set(progress.get("seen", []))
                        if len(set(numbers)) != len(numbers) or seen.intersection(numbers):
                            raise ValueError("GitHub search repeated PR IDs")
                        progress["seen"] = sorted(seen.union(numbers))
                        progress["pending"] = numbers
                        if progress["page"] * 100 >= data["total_count"]:
                            progress["ranges"].pop(0)
                            progress["page"] = 1
                        else:
                            if len(data["items"]) != 100:
                                raise ValueError("GitHub search pagination is incomplete")
                            progress["page"] += 1
                if not self._save(row, progress):
                    return False  # A replacement claim owns the cursor now.
                remaining = response.headers.get("X-RateLimit-Remaining", "")
                if remaining.isdigit() and int(remaining) <= 100:
                    # Reserve core requests for engineering workflows. Search has
                    # a smaller bucket, so use its own exhausted threshold.
                    resource = response.headers.get("X-RateLimit-Resource", "core")
                    if resource != "search" or int(remaining) <= 1:
                        try:
                            reset = float(response.headers.get("X-RateLimit-Reset", 0))
                        except ValueError:
                            reset = 0
                        self.pause_until = max(self.clock() + 60, reset)
                        self._save(
                            row, progress, state="queued", delay=self.pause_until - self.clock()
                        )
                        with self.store.connect() as db:
                            db.execute(
                                "UPDATE analytics_months SET next_retry=:until WHERE state IN ('queued','retry') AND next_retry<:until",
                                {"until": self.pause_until},
                            )
                        return True
            self._save(row, progress, state="queued")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError) as error:
            status = (
                error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
            )
            delay = min(3600, 30 * 2 ** min(row["attempts"], 7))
            if isinstance(error, httpx.HTTPStatusError):
                try:
                    delay = max(
                        delay,
                        float(error.response.headers.get("Retry-After", 0)),
                        float(error.response.headers.get("X-RateLimit-Reset", 0)) - self.clock(),
                    )
                except ValueError:
                    pass
            state = (
                "blocked" if status in (401, 404) or isinstance(error, OverflowError) else "retry"
            )
            if row["attempts"] >= 7:
                state = "dead_letter"
            progress["error"] = f"GitHub HTTP {status}" if status else type(error).__name__
            self._save(row, progress, state=state, delay=delay, failed=True)
        return True
