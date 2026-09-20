"""Persist only public PR metadata; Superset reads a curated Postgres view."""

import json
import sqlite3
from pathlib import Path

from ..database import Database
from ..schema import analytics


class AnalyticsStore:
    def __init__(self, path, *, seed: Path | None = None):
        self.path = str(path)
        self.database = Database(path)
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

    def upsert(self, repository, pulls):
        records = [
            {
                "number": pr["number"],
                "title": pr["title"],
                "url": pr["html_url"],
                "author": (pr.get("user") or {}).get("login", "deleted-user"),
                "labels": [label["name"] for label in pr.get("labels", [])],
                "base": pr["base"]["ref"],
                "state": pr["state"],
                **{
                    key: pr.get(key)
                    for key in ("created_at", "updated_at", "closed_at", "merged_at")
                },
            }
            for pr in pulls
        ]
        with self.connect() as db:
            db.executemany(
                "INSERT INTO pull_requests(repository,number,data) VALUES(:repository,:number,:data) ON CONFLICT(repository,number) DO UPDATE SET data=excluded.data",
                [
                    {"repository": repository, "number": pr["number"], "data": json.dumps(pr)}
                    for pr in records
                ],
            )

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
            return json.loads(row["data"]) if row else {"state": "not_synced"}

    def set_status(self, repository, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sync_status(repository,data) VALUES(:repository,:data) ON CONFLICT(repository) DO UPDATE SET data=excluded.data",
                {"repository": repository, "data": json.dumps(value)},
            )
