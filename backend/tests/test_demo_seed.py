import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

from app.automation.config import Settings
from app.demo_seed import SEED_PATH, build_seed
from app.main import create_app
from fastapi.testclient import TestClient


def contents(path):
    with closing(sqlite3.connect(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        fixtures = connection.execute("SELECT key,value FROM fixtures ORDER BY key").fetchall()
    return tables, events, fixtures


def test_committed_seed_is_synthetic_and_rebuildable(tmp_path):
    generated = tmp_path / "rebuilt.sqlite3"
    build_seed(generated)
    assert contents(generated) == contents(SEED_PATH)
    tables, events, fixtures = contents(SEED_PATH)
    assert tables == {"fixtures", "events"}
    assert events == 0
    assert len(fixtures) == 1
    dashboard = json.loads(fixtures[0][1])
    assert dashboard["mode"] == "demo"
    assert len(dashboard["workflows"]) == 5
    assert dashboard["candidate"]["status"] == "needs_review"


def test_fresh_clone_uses_seed_and_never_modifies_it(tmp_path):
    before = hashlib.sha256(SEED_PATH.read_bytes()).hexdigest()
    database = tmp_path / "demo.db"
    app = create_app(
        replace(Settings(), database=str(tmp_path / "live.db")), demo_database=database
    )
    with TestClient(app) as client:
        assert client.get("/api/dashboard").json()["candidate"]["status"] == "needs_review"
        assert (
            client.post(
                "/api/demo/events", json={"delivery_id": "sample", "title": "Local demo event"}
            ).status_code
            == 200
        )
        assert len(client.get("/api/dashboard").json()["events"]) == 1
        assert client.get("/api/live/overview").json()["jobs"] == []
    assert hashlib.sha256(SEED_PATH.read_bytes()).hexdigest() == before
    # Restart preserves local interactions while the committed seed remains pristine.
    with TestClient(app) as client:
        assert len(client.get("/api/dashboard").json()["events"]) == 1
