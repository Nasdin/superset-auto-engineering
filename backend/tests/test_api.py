from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.demo_fixtures import SHA
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(
        replace(Settings(), database=str(tmp_path / "live.db")), demo_database=tmp_path / "test.db"
    )
    with TestClient(app) as client:
        yield client


def test_dashboard_marks_fixtures(client):
    data = client.get("/api/dashboard").json()
    assert data["mode"] == "demo"
    assert len(data["candidate"]["sha"]) == 40
    assert len(data["workflows"]) == 5


def test_health_checks_live_store_without_claiming_automation_is_enabled(client):
    assert client.get("/api/health").json() == {
        "status": "ok",
        "mode": "live",
        "automation_enabled": False,
    }
    assert client.get("/api/demo/health").json()["mode"] == "demo"


def test_stale_sha_rejected_without_decision(client):
    result = client.post(
        "/api/demo/decisions", json={"sha": "stale", "decision": "approved", "note": "reviewed"}
    )
    assert result.status_code == 409
    assert client.get("/api/dashboard").json()["events"] == []


def test_valid_decision_persists_but_never_merges(client):
    result = client.post(
        "/api/demo/decisions", json={"sha": SHA, "decision": "approved", "note": "reviewed fixture"}
    )
    assert result.json()["merged"] is False
    events = client.get("/api/dashboard").json()["events"]
    assert events[0]["payload"]["sha"] == SHA
    assert events[0]["kind"] == "demo_decision"


def test_duplicate_events_are_atomic(client):
    client.get("/api/health")
    payload = {"delivery_id": "same-delivery", "title": "Fix query regression"}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: client.post("/api/demo/events", json=payload).json(), range(8))
        )
    assert sum(r["status"] == "queued" for r in results) == 1
    assert len(client.get("/api/dashboard").json()["events"]) == 1


def test_live_approval_blocked(client):
    assert client.post("/api/releases/approve").status_code == 409


def test_invalid_decisions_rejected(client):
    assert (
        client.post(
            "/api/demo/decisions", json={"sha": SHA, "decision": "merge", "note": "x"}
        ).status_code
        == 422
    )
