"""Read-only, resumable GitHub detail import with explicit incomplete measurements.

The list endpoint omits line counts, commit totals and reviews. This worker has
its own request budget and never starts a Devin session. A failed/truncated scan
is unknown, not zero. The GitHub PR-commits endpoint has a 250-commit ceiling.
"""

import argparse
import json
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import httpx

from ..automation.config import Settings
from .metrics import category
from .store import DETAIL_FIELDS, AnalyticsStore

DETAIL_COUNTS = {
    "commits_count": "commits",
    "additions": "additions",
    "deletions": "deletions",
    "changed_files": "changed_files",
}


class Incomplete(ValueError):
    """A bounded or invalid response cannot establish a complete measurement."""


class SnapshotChanged(Incomplete):
    """GitHub proved that stored detail measurements describe an older revision."""


class BudgetExhausted(Incomplete):
    """Stop this run rather than spend the repository's rate-limit reserve."""


def timestamp(value):
    if not isinstance(value, str):
        raise Incomplete("Missing timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Incomplete("Invalid timestamp") from error
    if result.tzinfo is None:
        raise Incomplete("Timestamp has no timezone")
    return result.astimezone(UTC)


def count(value):
    return value if type(value) is int and value >= 0 else None


class GitHubReader:
    def __init__(self, client, *, max_requests=400, rate_limit_reserve=100, max_pages=10):
        self.client = client
        self.remaining = max_requests
        self.requests = 0
        self.rate_limit_reserve = rate_limit_reserve
        self.max_pages = max_pages
        self.stopped = False

    def get(self, url, **kwargs):
        if self.remaining <= 0 or self.stopped:
            raise BudgetExhausted("Request budget or rate-limit reserve reached")
        self.remaining -= 1
        self.requests += 1
        response = self.client.get(url, **kwargs)
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.stopped = int(remaining) <= self.rate_limit_reserve
        if response.status_code in (403, 429):
            self.stopped = True
        response.raise_for_status()
        return response

    def collection(self, url):
        rows = []
        for page in range(1, self.max_pages + 1):
            response = self.get(url, params={"per_page": 100, "page": page})
            items = response.json()
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                raise Incomplete("Invalid collection")
            rows.extend(items)
            # GitHub Link is authoritative when supplied. Without it, a full
            # page is followed conservatively to avoid treating truncation as zero.
            if "next" not in response.links:
                if "link" in response.headers or len(items) < 100:
                    return rows
                # Some proxies omit Link; request the next page conservatively.
        raise Incomplete("Pagination limit reached")


def measure(pr, repository, reader, now):
    root = f"https://api.github.com/repos/{repository}/pulls/{pr['number']}"
    result = {key: None for key in DETAIL_COUNTS}
    result.update(
        first_review_at=None,
        rework_commits=None,
        details_updated_at=now.isoformat(),
        enrichment_state="partial",
        enrichment_error=None,
    )
    detail = reader.get(root).json()
    if not isinstance(detail, dict):
        raise Incomplete("Invalid PR detail")
    if detail.get("updated_at") != pr.get("updated_at"):
        raise SnapshotChanged("PR changed since list refresh")
    result.update({key: count(detail.get(source)) for key, source in DETAIL_COUNTS.items()})
    result["author_type"] = (detail.get("user") or {}).get("type") or pr.get("author_type")
    try:
        reviews = reader.collection(root + "/reviews")
        submitted = []
        for review in reviews:
            if review.get("state") == "PENDING":
                continue
            user = review.get("user") or {}
            if user.get("type") == "Bot" or user.get("login") == pr.get("author"):
                continue
            # Deleted/unknown reviewers must not silently count as human, nor
            # establish zero rework. Their type cannot be inferred from a name.
            if user.get("type") != "User" or not user.get("login"):
                raise Incomplete("Unknown review author type")
            submitted.append(timestamp(review.get("submitted_at")))
        first = min(submitted) if submitted else None
        result["first_review_at"] = first.isoformat() if first else None
        if first is None:
            result["rework_commits"] = 0
        else:
            total = result["commits_count"]
            if total is None or total > 250:
                raise Incomplete(
                    "Commit history unavailable or exceeds GitHub's 250-commit ceiling"
                )
            commits = reader.collection(root + "/commits")
            if (
                len(commits) != total
                or any(not row.get("sha") for row in commits)
                or len({row.get("sha") for row in commits}) != total
            ):
                raise Incomplete("Commit history does not match PR total")
            cutoff = timestamp(pr["merged_at"]) if pr.get("merged_at") else now
            dates = [
                timestamp(((row.get("commit") or {}).get("committer") or {}).get("date"))
                for row in commits
            ]
            result["rework_commits"] = sum(first < value <= cutoff for value in dates)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        result["enrichment_error"] = safe_error(error)
    if (
        all(result[key] is not None for key in DETAIL_COUNTS)
        and result["rework_commits"] is not None
    ):
        result["enrichment_state"] = "complete"
    return result


def safe_error(error):
    # Avoid recording URLs, response bodies, tokens or arbitrary provider text.
    if isinstance(error, httpx.HTTPStatusError):
        return f"GitHub HTTP {error.response.status_code}"
    if isinstance(error, Incomplete):
        return str(error)
    return type(error).__name__


def eligible_pulls(pulls, now, history_days):
    horizon = now - timedelta(days=history_days)
    result = []
    for pr in pulls:
        try:
            # Merged cohorts drive the dashboard; recently active open PRs are
            # retained after merged PRs for later merge/cohort completeness.
            event = timestamp(pr.get("merged_at") or pr.get("updated_at"))
        except Incomplete:
            continue
        if horizon <= event <= now:
            result.append(pr)
    return result


def candidates(pulls, now):
    """Round-robin month/category cohorts so backfill does not hide older months."""
    buckets = defaultdict(deque)
    for pr in sorted(
        pulls, key=lambda row: row.get("merged_at") or row.get("updated_at") or "", reverse=True
    ):
        state = pr.get("enrichment_state", "pending")
        if state == "complete":
            continue
        if state in ("error", "partial") and pr.get("details_updated_at"):
            try:
                if timestamp(pr["details_updated_at"]) > now - timedelta(days=1):
                    continue
            except Incomplete:
                pass
        event = pr.get("merged_at") or pr.get("updated_at")
        # Pending/stale precede retries; merged precede open. Every month and
        # work category gets a turn before any bucket receives its second PR.
        key = (
            state in ("error", "partial"),
            not bool(pr.get("merged_at")),
            event[:7],
            category(pr),
        )
        buckets[key].append(pr)
    for priority in ((False, False), (False, True), (True, False), (True, True)):
        keys = sorted((key for key in buckets if key[:2] == priority), reverse=True)
        while any(buckets[key] for key in keys):
            for key in keys:
                if buckets[key]:
                    yield buckets[key].popleft()


def enrich_repository(
    store,
    repository,
    client,
    *,
    now=None,
    max_prs=100,
    max_requests=400,
    history_days=400,
    rate_limit_reserve=100,
    max_pages=10,
):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    if min(max_prs, max_requests, history_days, max_pages) < 1 or rate_limit_reserve < 0:
        raise ValueError("Enrichment bounds must be positive")
    now = now or datetime.now(UTC)
    reader = GitHubReader(
        client,
        max_requests=max_requests,
        rate_limit_reserve=rate_limit_reserve,
        max_pages=max_pages,
    )
    eligible = eligible_pulls(store.pulls(repository), now, history_days)
    processed = 0
    for pr in candidates(eligible, now):
        if processed >= max_prs or reader.remaining <= 0 or reader.stopped:
            break
        try:
            measurements = measure(pr, repository, reader, now)
        except SnapshotChanged as error:
            # Unlike a transient network error, a provider version mismatch
            # proves previously retained counts/reviews are no longer current.
            measurements = {
                **dict.fromkeys(DETAIL_FIELDS),
                "enrichment_state": "stale",
                "enrichment_error": safe_error(error),
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            measurements = {
                "enrichment_state": "error",
                "enrichment_error": safe_error(error),
                "details_updated_at": now.isoformat(),
            }
        store.enrich(
            repository, pr["number"], measurements, expected_updated_at=pr.get("updated_at")
        )
        processed += 1
    eligible = eligible_pulls(store.pulls(repository), now, history_days)
    complete = sum(pr.get("enrichment_state") == "complete" for pr in eligible)
    partial = sum(pr.get("enrichment_state") == "partial" for pr in eligible)
    progress = {
        "state": "complete" if complete == len(eligible) else "partial",
        "eligible": len(eligible),
        "complete": complete,
        "partial": partial,
        "errors": sum(pr.get("enrichment_state") == "error" for pr in eligible),
        "remaining": len(eligible) - complete,
        "processed": processed,
        "requests": reader.requests,
        "rate_limited": reader.stopped,
        "history_days": history_days,
        "last_run": now.isoformat(),
        "sampling": "Round-robin merge month and work category; incomplete cohorts are provisional",
    }
    store.set_status(repository, {**store.status(repository), "enrichment": progress})
    return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--max-prs", type=int, default=100)
    parser.add_argument("--max-requests", type=int, default=400)
    parser.add_argument("--history-days", type=int, default=400)
    parser.add_argument("--rate-limit-reserve", type=int, default=100)
    args = parser.parse_args()
    settings = Settings.from_env()
    store = AnalyticsStore(settings.analytics_database)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    with httpx.Client(headers=headers, timeout=45) as client:
        print(
            json.dumps(
                enrich_repository(
                    store,
                    args.repository,
                    client,
                    max_prs=args.max_prs,
                    max_requests=args.max_requests,
                    history_days=args.history_days,
                    rate_limit_reserve=args.rate_limit_reserve,
                )
            )
        )


if __name__ == "__main__":
    main()
