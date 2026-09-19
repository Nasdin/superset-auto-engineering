from dataclasses import replace
import hashlib
import hmac
import json
from fastapi.testclient import TestClient
from app.main import app
from app.automation import routes
from app.automation.store import Store


def setup(monkeypatch, tmp_path):
    s = replace(
        routes.settings,
        database=str(tmp_path / "test.db"),
        webhook_secret="test-secret",
        operator_token="test-operator",
    )
    monkeypatch.setattr(routes, "settings", s)
    return TestClient(app), s


def test_webhook_rejects_unsigned_and_wrong_repo(monkeypatch, tmp_path):
    client, s = setup(monkeypatch, tmp_path)
    assert client.post("/api/live/webhooks/github", content="{}").status_code == 401
    body = json.dumps(
        {"repository": {"full_name": "apache/superset"}, "sender": {"login": "Nasdin"}}
    ).encode()
    sig = (
        "sha256="
        + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )
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
        db = Store(s.database)

        def accept_issue(self, number, source):
            return self.db.enqueue(
                "issue:1", "repair", {"issue_number": number, "source": source}
            )

    monkeypatch.setattr(routes, "engine", Engine)
    body = json.dumps(
        {
            "repository": {"full_name": s.repo},
            "sender": {"login": s.allowed_actor},
            "action": "labeled",
            "issue": {"number": 1, "labels": [{"name": s.label}]},
        }
    ).encode()
    sig = (
        "sha256="
        + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Delivery": "abc",
        "X-GitHub-Event": "issues",
    }
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()[
            "status"
        ]
        == "accepted"
    )
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()[
            "status"
        ]
        == "duplicate"
    )
    assert len(Engine.db.jobs()) == 1


def test_operator_mutations_require_auth(monkeypatch, tmp_path):
    client, s = setup(monkeypatch, tmp_path)
    assert client.post("/api/live/scan").status_code == 401
    assert client.post("/api/live/issues", json={"number": 1}).status_code == 401
