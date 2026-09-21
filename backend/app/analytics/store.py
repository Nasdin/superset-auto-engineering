"""Persist only public PR metadata; Superset reads a curated Postgres view."""

import json
import sqlite3
from pathlib import Path

from ..database import Database
from ..schema import analytics

DETAIL_FIELDS = (
    "commits_count",
    "additions",
    "deletions",
    "changed_files",
    "first_review_at",
    "rework_commits",
    "details_updated_at",
)


class AnalyticsStore:
    def __init__(self, path, *, seed: Path | None = None):
        self.path = str(path)
        self.database = Database(path)
        try:
            self._initialize(seed)
        except Exception:
            self.database.close()
            raise

    def _initialize(self, seed: Path | None):
        self.database.initialize(analytics)
        if seed is not None and seed.is_file():
            # Historic, read-only public snapshot. Runtime writes use DATABASE_URL.
            with self.connect() as db:
                db.lock()
                if (
                    not db.execute("SELECT 1 FROM pull_requests LIMIT 1").fetchone()
                    and not db.execute("SELECT 1 FROM sync_status LIMIT 1").fetchone()
                ):
                    with sqlite3.connect(
                        seed.resolve().as_uri() + "?mode=ro", uri=True
                    ) as snapshot:
                        db.executemany(
                            "INSERT INTO pull_requests(repository,number,data) VALUES(:repository,:number,:data)",
                            [
                                {"repository": r, "number": n, "data": d}
                                for r, n, d in snapshot.execute("SELECT * FROM pull_requests")
                            ],
                        )
                        db.executemany(
                            "INSERT INTO sync_status(repository,data) VALUES(:repository,:data)",
                            [
                                {"repository": r, "data": d}
                                for r, d in snapshot.execute("SELECT * FROM sync_status")
                            ],
                        )

    def connect(self):
        return self.database.connect()

    @staticmethod
    def bump(db, repository):
        db.execute(
            "INSERT INTO analytics_revisions(repository,revision) VALUES(:repository,1) "
            "ON CONFLICT(repository) DO UPDATE SET revision=analytics_revisions.revision+1",
            {"repository": repository},
        )

    def revision(self, repository):
        with self.connect() as db:
            row = db.execute(
                "SELECT revision FROM analytics_revisions WHERE repository=:repository",
                {"repository": repository},
            ).fetchone()
            return row["revision"] if row else 0

    def upsert(self, repository, pulls, *, month_claim=None):
        """Refresh list metadata without discarding detail measurements.

        Any provider update invalidates the snapshot, including updates to closed
        PRs. The next bounded enrichment pass rechecks them before analysis.
        """
        with self.connect() as db:
            db.lock()
            if month_claim is not None:
                month, token, now = month_claim
                if not db.execute(
                    "SELECT 1 FROM analytics_months WHERE repository=:repository AND month=:month "
                    "AND lease_token=:token AND lease_until>:now AND state='running'",
                    {"repository": repository, "month": month, "token": token, "now": now},
                ).fetchone():
                    return False
            records = []
            for pr in pulls:
                previous = db.execute(
                    "SELECT data FROM pull_requests WHERE repository=:repository AND number=:number",
                    {"repository": repository, "number": pr["number"]},
                ).fetchone()
                record = json.loads(previous["data"]) if previous else {}
                changed = bool(record) and any(
                    record.get(key) != pr.get(key) for key in ("updated_at", "merged_at", "state")
                )
                if changed:
                    record.update(dict.fromkeys(DETAIL_FIELDS))
                    record["enrichment_state"] = "stale"
                    record.pop("enrichment_error", None)
                record.update(
                    {
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["html_url"],
                        "author": (pr.get("user") or {}).get("login", "deleted-user"),
                        "author_type": (pr.get("user") or {}).get("type")
                        or record.get("author_type"),
                        "labels": [label["name"] for label in pr.get("labels", [])],
                        "base": pr["base"]["ref"],
                        "state": pr["state"],
                        **{
                            key: pr.get(key)
                            for key in ("created_at", "updated_at", "closed_at", "merged_at")
                        },
                    }
                )
                record.setdefault("enrichment_state", "pending")
                records.append(
                    {"repository": repository, "number": pr["number"], "data": json.dumps(record)}
                )
            db.executemany(
                "INSERT INTO pull_requests(repository,number,data) VALUES(:repository,:number,:data) "
                "ON CONFLICT(repository,number) DO UPDATE SET data=excluded.data",
                records,
            )

            if records:
                self.bump(db, repository)
            return True

    def enrich(self, repository, number, measurements, *, expected_updated_at):
        """Publish only if the list snapshot has not changed during HTTP requests."""
        with self.connect() as db:
            db.lock()
            parameters = {"repository": repository, "number": number}
            row = db.execute(
                "SELECT data FROM pull_requests WHERE repository=:repository AND number=:number",
                parameters,
            ).fetchone()
            if not row:
                return False
            record = json.loads(row["data"])
            if record.get("updated_at") != expected_updated_at:
                return False
            record.update(measurements)
            db.execute(
                "UPDATE pull_requests SET data=:data WHERE repository=:repository AND number=:number",
                {**parameters, "data": json.dumps(record)},
            )
            self.bump(db, repository)
            return True

    def pulls(self, repository):
        with self.connect() as db:
            return [
                json.loads(row["data"])
                for row in db.execute(
                    "SELECT data FROM pull_requests WHERE repository=:repository",
                    {"repository": repository},
                )
            ]

    def status(self, repository):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM sync_status WHERE repository=:repository",
                {"repository": repository},
            ).fetchone()
            status = json.loads(row["data"]) if row else {"state": "not_synced"}
            status["months"] = [
                dict(item)
                for item in db.execute(
                    "SELECT month,covered_through,state FROM analytics_months WHERE repository=:repository",
                    {"repository": repository},
                )
            ]
            return status

    def set_status(self, repository, value):
        value = {key: item for key, item in value.items() if key != "months"}
        with self.connect() as db:
            db.execute(
                "INSERT INTO sync_status(repository,data) VALUES(:repository,:data) ON CONFLICT(repository) DO UPDATE SET data=excluded.data",
                {"repository": repository, "data": json.dumps(value)},
            )
            self.bump(db, repository)
