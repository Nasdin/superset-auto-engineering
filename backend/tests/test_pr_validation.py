import copy
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.pr_validation import PullRequestValidationService
from app.automation.providers import ProviderError
from app.automation.store import Store
from test_automation import SHA, FakeProvider, result


class PullRequestProvider(FakeProvider):
    def __init__(self, settings):
        self.document = {
            "number": 8,
            "title": "Fix query behavior",
            "state": "open",
            "draft": False,
            "user": {"login": "Nasdin", "type": "User"},
            "labels": [{"name": "cognition:validate"}],
            "base": {"repo": {"full_name": settings.repo}, "ref": settings.branch, "sha": "b" * 40},
            "head": {"repo": {"full_name": settings.repo}, "ref": "engineer/fix", "sha": SHA},
        }
        self.created = 0
        self.comments = []
        self.payloads = []

    def pr(self, number):
        return copy.deepcopy(self.document)

    def create_session(self, payload):
        self.payloads.append(payload)
        data = super().create_session(payload)
        return {**data, "session_id": f"validator-{self.created}"}


@pytest.fixture
def setup(tmp_path):
    settings = replace(
        Settings(),
        database=str(tmp_path / "jobs.db"),
        enabled=True,
        devin_key="test",
        github_token="test",
    )
    store = Store(settings.database)
    provider = PullRequestProvider(settings)
    engine = Engine(settings, store, provider)
    return store, provider, engine, PullRequestValidationService(settings, store, provider)


def test_engineer_pr_fresh_validator_publishes_complete_reply_once(setup):
    store, p, engine, service = setup
    job = service.accept(8, "webhook", SHA)
    assert service.accept(8, "poll")["id"] == job["id"]
    engine.tick()
    job = store.get(job["id"])
    engine.finish_validation(job, result())
    assert store.get(job["id"])["state"] == "review_ready"
    engine.flush_publication()
    engine.flush_publication()
    assert len(p.comments) == 1 and p.comments[0][0] == 8
    assert "curl -X POST" in p.comments[0][1] and "80/100 (80.0%)" in p.comments[0][1]
    assert store.publications()[0]["state"] == "sent"
    assert "coverage" in p.payloads[0]["structured_output_schema"]["required"]


def test_external_pr_requires_audited_new_session_not_arbitrary_session_claim(setup):
    store, p, engine, service = setup
    job = service.accept(8, "webhook")
    store.update(
        job["id"],
        session_id="unproven",
        session_url="https://app.devin.ai/sessions/unproven",
        state="running",
    )
    engine.finish_validation(store.get(job["id"]), result())
    assert store.get(job["id"])["state"] == "validation_failed"


def test_managed_devin_pr_engineer_push_queues_current_head_validation(setup):
    store, p, engine, service = setup
    repair = store.enqueue(
        "repair", "repair", {"issue_number": 3}, candidate_sha="c" * 40, pr_number=8
    )
    store.update(repair["id"], state="implemented", session_id="implementation")
    p.document["user"] = {"login": "devin-ai-integration[bot]", "type": "Bot"}
    p.document["labels"] = []
    job = service.accept(8, "synchronize", SHA)
    assert job["kind"] == "validation" and job["candidate_sha"] == SHA
    assert job["payload"]["prior_implementation_shas"] == ["c" * 40]
    engine.tick()
    engine.finish_validation(store.get(job["id"]), result())
    assert store.get(job["id"])["state"] == "review_ready"


def test_old_event_and_foreign_head_cannot_validate(setup):
    store, p, engine, service = setup
    assert service.accept(8, "webhook", "d" * 40)["status"] == "ignored"
    p.document["head"]["repo"]["full_name"] = "attacker/superset"
    with pytest.raises(ValueError):
        service.accept(8, "webhook")
    assert not store.jobs()


def test_current_head_is_checked_again_before_post_and_old_success_not_sent(setup):
    store, p, engine, service = setup
    job = service.accept(8, "webhook")
    engine.tick()
    engine.finish_validation(store.get(job["id"]), result())
    p.document["head"]["sha"] = "d" * 40
    engine.flush_publication()
    assert not p.comments and store.publications()[0]["state"] == "stale"
    assert store.get(job["id"])["state"] == "stale"
    assert len([j for j in store.jobs() if j["state"] == "queued"]) == 1


def test_read_outage_before_comment_retries_without_posting(setup):
    store, p, engine, service = setup
    job = service.accept(8, "webhook")
    engine.tick()
    engine.finish_validation(store.get(job["id"]), result())
    original = p.pr

    def unavailable(number):
        raise ProviderError("read failed")

    p.pr = unavailable
    engine.flush_publication()
    assert not p.comments and store.publications()[0]["state"] == "pending"
    p.pr = original
    engine.flush_publication()
    assert len(p.comments) == 1


def test_receipt_only_retry_does_not_repeat_post_after_head_changes(setup):
    store, p, engine, service = setup
    job = service.accept(8, "webhook")
    engine.tick()
    engine.finish_validation(store.get(job["id"]), result())
    confirm = p.confirm_publication

    def unavailable(*args):
        raise ProviderError("readback failed")

    p.confirm_publication = unavailable
    engine.flush_publication()
    assert len(p.comments) == 1 and store.publications()[0]["state"] == "delivered"
    p.document["head"]["sha"] = "d" * 40
    p.confirm_publication = confirm
    engine.flush_publication()
    assert len(p.comments) == 1 and store.publications()[0]["state"] == "sent"


def test_changed_integration_keeps_member_sessions_for_independence(setup):
    store, p, engine, service = setup
    repair = store.enqueue("repair", "repair", {}, candidate_sha="c" * 40, pr_number=2)
    store.update(repair["id"], state="implemented", session_id="validator-1")
    integration = store.enqueue(
        "integration",
        "integration",
        {"members": [{"job_id": repair["id"], "pr_number": 2, "issue_number": 1, "sha": "c" * 40}]},
        candidate_sha="d" * 40,
        pr_number=8,
    )
    store.update(integration["id"], state="integrated")
    job = service.accept(8, "synchronize", SHA)
    assert job["payload"]["implementation_jobs"] == [repair["id"]]
    engine.tick()
    engine.finish_validation(store.get(job["id"]), result())
    assert store.get(job["id"])["state"] == "validation_failed"


@pytest.mark.parametrize("author", ["Nasdin", "devin-ai-integration[bot]"])
def test_signed_pr_change_event_to_validation_and_confirmed_reply(setup, tmp_path, author):
    import hashlib
    import hmac
    import json

    from app.automation import routes
    from app.main import create_app
    from fastapi.testclient import TestClient

    store, p, engine, service = setup
    engine.settings = replace(engine.settings, webhook_secret="signed-event-test")
    app = create_app(engine.settings, demo_database=tmp_path / "demo.db")
    app.dependency_overrides[routes.get_engine] = lambda: engine
    p.document["user"]["login"] = author
    client = TestClient(app)

    def deliver(sha, delivery):
        body = json.dumps(
            {
                "repository": {"full_name": engine.settings.repo},
                "sender": {"login": author},
                "action": "synchronize",
                "pull_request": {"number": 8, "head": {"sha": sha}},
            }
        ).encode()
        headers = {
            "X-Hub-Signature-256": "sha256="
            + hmac.new(engine.settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest(),
            "X-GitHub-Delivery": delivery,
            "X-GitHub-Event": "pull_request",
        }
        response = client.post("/api/live/webhooks/github", content=body, headers=headers)
        assert response.status_code == 200
        return response.json()

    first = deliver(SHA, "first")
    assert first["status"] == "accepted"
    assert deliver(SHA, "first")["status"] == "duplicate"
    engine.tick()
    engine.finish_validation(store.get(first["job_id"]), result())
    engine.flush_publication()
    assert len(p.comments) == 1
    p.document["head"]["sha"] = "d" * 40
    second = deliver("d" * 40, "second")
    assert second["status"] == "accepted" and second["job_id"] != first["job_id"]
    engine.tick()
    evidence = result()
    evidence["candidate_sha"] = "d" * 40
    engine.finish_validation(store.get(second["job_id"]), evidence)
    engine.flush_publication()
    assert store.get(first["job_id"])["state"] == "stale"
    assert store.get(second["job_id"])["state"] == "review_ready"
    assert len(p.comments) == 2 and "d" * 40 in p.comments[-1][1]
