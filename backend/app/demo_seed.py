"""Reproducible, synthetic SQLite seed shipped with the application.

Run `python -m app.demo_seed` from backend to rebuild the committed seed.
No environment variables or live execution records are read.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .demo_fixtures import CHECKS, SHA, WORKFLOWS

SEED_PATH = Path(__file__).parent / "seeds" / "demo.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, delivery TEXT UNIQUE, kind TEXT, payload TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS fixtures (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def build_seed(path: Path = SEED_PATH) -> None:
    fixture = {
        "mode": "demo",
        "repository": "apache/superset",
        "candidate": {
            "id": "RC-014",
            "sha": SHA,
            "branch": "integration/rc-014",
            "validator": "DV-086",
            "status": "needs_review",
        },
        "checks": CHECKS,
        "workflows": WORKFLOWS,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM events")
        connection.execute("DELETE FROM fixtures")
        connection.execute(
            "INSERT INTO fixtures VALUES ('dashboard', ?)",
            (json.dumps(fixture, sort_keys=True),),
        )
        connection.commit()
        connection.execute("VACUUM")
    print(f"Built synthetic demo seed: {path}")


if __name__ == "__main__":
    build_seed()
