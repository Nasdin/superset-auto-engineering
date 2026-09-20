import hashlib
import hmac
import json
from dataclasses import replace

from app.automation import routes
from app.automation.store import Store
from app.main import create_app
from fastapi.testclient import TestClient


def setup(monkeypatch, tmp_path):
    s = replace(
        routes.Settings(),
        database=str(tmp_path / "test.db"),
        webhook_secret="test-secret",
        operator_token="test-operator",
    )
    app = create_app(s, demo_database=tmp_path / "demo.db")
    eng = routes.Engine(s, Store(s.database), None)
    app.dependency_overrides[routes.get_engine] = lambda: eng
    return TestClient(app), s


def test_webhook_rejects_unsigned_and_wrong_repo(monkeypatch, tmp_path):
    client, s = setup(monkeypatch, tmp_path)
    assert client.post("/api/live/webhooks/github", content="{}").status_code == 401
    body = json.dumps(
        {"repository": {"full_name": "apache/superset"}, "sender": {"login": "Nasdin"}}
    ).encode()
    sig = "sha256=" + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    assert (
        client.post(
            "/api/live/webhooks/github",
            content=body,
            headers={"X-Hub-Signature-256": sig, "X-GitHub-Delivery": "abc"},
        ).status_code
        == 403
    )


def test_valid_webhook_is_deduplicated(monkeypatch, tmp_path):
    client, s = setup(monkeypatch, tmp_path)

    class Engine:
        store = Store(s.database)
        settings = s

        accept_webhook = routes.Engine.accept_webhook

        def accept_issue(self, number, source):
            return self.store.enqueue(
                "issue:1", "repair", {"issue_number": number, "source": source}
            )

    client.app.dependency_overrides[routes.get_engine] = lambda: Engine()
    body = json.dumps(
        {
            "repository": {"full_name": s.repo},
            "sender": {"login": s.allowed_actor},
            "action": "labeled",
            "issue": {"number": 1, "labels": [{"name": s.label}]},
        }
    ).encode()
    sig = "sha256=" + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Delivery": "abc",
        "X-GitHub-Event": "issues",
    }
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()["status"]
        == "accepted"
    )
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()["status"]
        == "duplicate"
    )
    assert len(Engine.store.jobs()) == 1


def test_operator_mutations_require_auth(monkeypatch, tmp_path):
    client, s = setup(monkeypatch, tmp_path)
    assert client.post("/api/live/scan").status_code == 401
    assert client.post("/api/live/issues", json={"number": 1}).status_code == 401


def signed_headers(settings, body):
    return {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest(),
        "X-GitHub-Delivery": "malformed-delivery",
        "X-GitHub-Event": "issues",
    }


def test_webhook_rejects_malformed_nested_payload(monkeypatch, tmp_path):
    client, settings = setup(monkeypatch, tmp_path)
    for payload in [
        {"repository": []},
        {
            "repository": {"full_name": settings.repo},
            "sender": {"login": settings.allowed_actor},
            "issue": {"number": -1},
        },
    ]:
        body = json.dumps(payload).encode()
        assert (
            client.post(
                "/api/live/webhooks/github", content=body, headers=signed_headers(settings, body)
            ).status_code
            == 422
        )
    assert client.post("/api/live/webhooks/github", content=b"x" * 1_000_001).status_code == 413


def test_provider_intake_runs_outside_event_loop(monkeypatch, tmp_path):
    import asyncio
    import threading

    import httpx

    client, settings = setup(monkeypatch, tmp_path)
    intake_threads = []

    class Intake:
        def accept_webhook(self, issue, delivery):
            intake_threads.append(threading.get_ident())
            return {"status": "accepted"}

    intake = Intake()
    intake.settings = settings
    client.app.dependency_overrides[routes.get_engine] = lambda: intake
    body = json.dumps(
        {
            "repository": {"full_name": settings.repo},
            "sender": {"login": settings.allowed_actor},
            "action": "opened",
            "issue": {"number": 1, "labels": [{"name": settings.label}]},
        }
    ).encode()

    async def exercise():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as session:
            response = await session.post(
                "/api/live/webhooks/github", content=body, headers=signed_headers(settings, body)
            )
        assert response.status_code == 200
        assert intake_threads and intake_threads[0] != loop_thread

    asyncio.run(exercise())
