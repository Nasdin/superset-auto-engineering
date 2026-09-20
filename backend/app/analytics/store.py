"""Public PR metadata, isolated from the credential-bearing automation ledger."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class AnalyticsStore:
    def __init__(self, path, *, seed: Path | None = None):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS pull_requests (
                    repository TEXT NOT NULL, number INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(repository, number));
                CREATE TABLE IF NOT EXISTS sync_status (
                    repository TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)

        if seed is not None and seed.is_file():
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if (
                    not db.execute("SELECT 1 FROM pull_requests LIMIT 1").fetchone()
                    and not db.execute("SELECT 1 FROM sync_status LIMIT 1").fetchone()
                ):
                    db.execute(
                        "ATTACH DATABASE ? AS snapshot", (seed.resolve().as_uri() + "?mode=ro",)
                    )
                    db.execute("INSERT INTO pull_requests SELECT * FROM snapshot.pull_requests")
                    db.execute("INSERT INTO sync_status SELECT * FROM snapshot.sync_status")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20, uri=True)
        try:
            with db:
                yield db
        finally:
            db.close()

    def upsert(self, repository, pulls):
        # Deliberate allowlist: no bodies, credentials, or provider response blobs.
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
                "INSERT INTO pull_requests VALUES(?,?,?) ON CONFLICT(repository,number) DO UPDATE SET data=excluded.data",
                [(repository, pr["number"], json.dumps(pr)) for pr in records],
            )

    def pulls(self, repository):
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM pull_requests WHERE repository=?", (repository,)
                )
            ]

    def status(self, repository):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM sync_status WHERE repository=?", (repository,)
            ).fetchone()
            return json.loads(row[0]) if row else {"state": "not_synced"}

    def set_status(self, repository, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sync_status VALUES(?,?) ON CONFLICT(repository) DO UPDATE SET data=excluded.data",
                (repository, json.dumps(value)),
            )
