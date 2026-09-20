"""Fault injection with disposable ledgers; never contacts paid providers."""

import time
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.pr_validation import PullRequestValidationService
from app.automation.providers import ProviderError, Providers, UnknownEffect, retry_delay
from app.automation.recovery_routes import replay
from app.automation.resilience import Recovery, backoff
from app.automation.store import Store
from app.automation.worker import cycle, singleton
from app.main import create_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_automation import FakeProvider, repair, result
from test_pr_validation import PullRequestProvider


@pytest.fixture
def system(tmp_path):
    s = replace(
        Settings(),
        database=str(tmp_path / "recovery.db"),
        enabled=True,
        github_token="test",
        devin_key="test",
        operator_token="owner",
    )
    db = Store(s.database)
    p = FakeProvider()
    p.comments = []
    p.created = 0
    yield db, p, Engine(s, db, p)
    db.database.close()


def due(db):
    with db.connect() as c:
        c.execute("UPDATE jobs SET next_poll=0")
        c.execute("UPDATE recovery SET next_retry=0")


def test_safe_rejection_backoff_survives_restart_and_exhausts(system):
    db, p, e = system
    j = repair(db)
    p.failure = ProviderError("rate limited", 429, retry_after=120)
    e.tick()
    r = Recovery(db).record("job:" + j["id"])
    assert r["next_retry"] >= time.time() + 119 and r["attempts"] == 1
    assert db.get(j["id"])["state"] == "queued"
    restarted = Engine(e.settings, db, p)
    restarted.tick()
    assert p.created == 1
    for _ in range(4):
        due(db)
        restarted.tick()
    assert db.get(j["id"])["state"] == "dead_letter" and p.created == 5
    restarted.tick()
    assert p.created == 5
    # One explicit intent resets retries without changing job identity.
    intent = uuid4()
    first = replay(e, "job", j["id"], intent)
    assert replay(e, "job", j["id"], intent) == first
    p.failure = None
    e.tick()
    assert db.get(j["id"])["session_id"] == "test-session"


def test_poll_dlq_replay_preserves_session_and_blocks_duplicate_paid_work(system):
    db, p, e = system
    j = repair(db)
    e.tick()
    p.failure = ProviderError("offline", 503)
    for _ in range(5):
        due(db)
        e.tick()
    assert db.get(j["id"])["state"] == "dead_letter"
    db.enqueue("another", "repair", {"base_sha": "a" * 40})
    assert db.claim() is None  # Unknown execution of existing paid work holds starts.
    replay(e, "job", j["id"], uuid4())
    assert db.get(j["id"])["state"] == "running"
    p.failure = None
    p.response = {"status": "running", "status_detail": "working"}
    e.tick()
    assert p.created == 1 and db.get(j["id"])["session_id"] == "test-session"


def test_uncertain_creation_is_never_a_retryable_dlq(system):
    db, p, e = system
    j = repair(db)
    p.failure = UnknownEffect("timeout")
    e.tick()
    with pytest.raises(HTTPException) as error:
        replay(e, "job", j["id"], uuid4())
    assert error.value.status_code == 409
    e.tick()
    assert p.created == 1


def test_credit_suspension_preserves_session_and_opens_paid_write_hold(system):
    db, p, e = system
    j = repair(db)
    e.tick()
    due(db)
    p.response = {"status": "suspended", "status_detail": "out_of_credits"}
    e.tick()
    assert db.get(j["id"])["state"] == "needs_attention"
    assert db.recall("breaker:devin")["reason"] == "credits"
    assert p.created == 1


def test_outbox_retry_confirmation_never_posts_twice_and_dlq_replays_receipt(system):
    db, p, e = system
    e.publish("job", 1, "report")
    original = p.confirm_publication
    p.confirm_publication = lambda *a: (_ for _ in ()).throw(ProviderError("read failure", 503))
    for _ in range(5):
        due(db)
        e.flush_publication()
    item = db.publications()[0]
    assert item["state"] == "dead_letter" and len(p.comments) == 1
    intent = uuid4()
    replay(e, "publication", item["key"], intent)
    replay(e, "publication", item["key"], intent)
    p.confirm_publication = original
    e.flush_publication()
    assert db.publications()[0]["state"] == "sent" and len(p.comments) == 1


def test_unknown_send_and_stale_gate_cannot_be_replayed(system):
    db, p, e = system
    e.publish("job", 1, "report")
    p.comment = lambda *a, **kw: (_ for _ in ()).throw(UnknownEffect("write timed out"))
    e.flush_publication()
    item = db.publications()[0]
    assert item["state"] == "unknown_effect"
    with pytest.raises(HTTPException):
        replay(e, "publication", item["key"], uuid4())
    j = repair(db)
    db.update(j["id"], state="stale")
    with pytest.raises(HTTPException):
        replay(e, "job", j["id"], uuid4())
    assert not db.commit_validation(j["id"], "review_ready", {}, None)


def test_execution_pause_keeps_observations_and_outbox_running(system):
    db, p, e = system
    j = repair(db)
    e.tick()
    due(db)
    paused = Engine(replace(e.settings, enabled=False), db, p)
    p.response = {"status": "running", "status_detail": "working"}
    # Keep independent scheduled services outside this focused kill-switch check.
    for key in ("learning_sync", "last_issue_poll"):
        db.remember(key, {"at": time.time()})
    e.publish(j["id"], 1, "already prepared report")
    cycle(paused)
    assert db.get(j["id"])["state"] == "running" and p.created == 1
    assert db.publications()[0]["state"] == "sent"
    db.update(j["id"], state="completed")
    db.enqueue("new", "repair", {})
    assert paused.tick() is None and p.created == 1


def test_singleton_rejects_overlapping_workers_and_releases_after_crash(tmp_path):
    with pytest.raises(RuntimeError):
        with singleton(tmp_path):
            with pytest.raises(BlockingIOError):
                with singleton(tmp_path):
                    pytest.fail("two workers acquired same volume")
            raise RuntimeError("worker crashed")
    with singleton(tmp_path):
        pass


def test_circuit_opens_after_three_read_failures_and_honors_retry_after(system):
    db, _, e = system
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503, json={})

    p = Providers(e.settings, client=httpx.Client(transport=httpx.MockTransport(respond)))
    p.store = db
    for _ in range(3):
        with pytest.raises(ProviderError):
            p.session("existing")
    with pytest.raises(ProviderError) as error:
        p.session("existing")
    assert error.value.category == "circuit_open" and len(calls) == 3
    assert db.recall("breaker:devin")["retry_at"] > time.time()
    replay(e, "provider", "devin", uuid4())
    p.client.close()
    p.client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "300"}))
    )
    with pytest.raises(ProviderError) as error:
        p.session("existing")
    assert error.value.retry_after == 300
    assert db.recall("breaker:devin")["retry_at"] >= time.time() + 299
    p.close()


def test_credit_circuit_allows_reads_not_writes_and_requires_operator_probe(system):
    db, _, e = system
    calls = []
    p = Providers(
        e.settings,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json={}))
        ),
    )
    p.store = db
    db.remember("breaker:devin", {"state": "open", "reason": "credits", "retry_at": 0})
    p.session("existing")
    with pytest.raises(ProviderError) as error:
        p.create_session({})
    assert error.value.category == "credits" and len(calls) == 1
    assert db.recall("breaker:devin")["state"] == "open"
    replay(e, "provider", "devin", uuid4())
    p.create_session({})
    assert len(calls) == 2
    p.close()


def test_permanent_artifact_error_does_not_retry_forever(system):
    db, _, _ = system
    j = repair(db)
    db.update(j["id"], state="running", session_id="existing")
    Recovery(db).job_failure(
        j, ProviderError("bad MIME", category="invalid_artifact", retryable=False), "archive"
    )
    assert db.get(j["id"])["state"] == "dead_letter"


def test_revision_changes_during_download_never_publishes_pass(system, monkeypatch):
    db, _, e = system
    p = PullRequestProvider(e.settings)
    e = Engine(e.settings, db, p)
    service = PullRequestValidationService(e.settings, db, p)
    j = service.accept(8, "test")
    e.tick()

    def download(self, artifacts, attachments):
        p.document["head"]["sha"] = "b" * 40
        return artifacts

    monkeypatch.setattr("app.automation.validation.EvidenceArchive.publish", download)
    e.finish_validation(db.get(j["id"]), result())
    assert db.get(j["id"])["state"] == "stale" and not db.publications()


def test_recovery_api_requires_owner_and_intents_are_durable(system, tmp_path):
    db, p, e = system
    j = repair(db)
    db.update(j["id"], state="dead_letter")
    app = create_app(e.settings, provider_factory=lambda s: Providers(s))
    with TestClient(app) as client:
        path = "/api/live/recovery/jobs/" + j["id"]
        body = {"request_id": str(uuid4())}
        assert client.post(path, json=body).status_code == 401
        headers = {"Authorization": "Bearer owner"}
        first = client.post(path, json=body, headers=headers)
        assert first.status_code == 200
        assert client.post(path, json=body, headers=headers).json() == first.json()
        status = client.get("/api/live/resilience").json()
        assert status["worker"]["stale"] and status["durability"]["backups_enabled"] is False
        assert status["retry_policy"]["max_attempts"] == 5


def test_backoff_and_retry_headers_are_bounded():
    assert 30 <= backoff(1) <= 37.5
    assert backoff(100) <= 1800
    assert backoff(1, 300) == 300
    assert retry_delay("invalid") == 0
    assert retry_delay("9999999") == 86400
    assert retry_delay("Wed, 01 Jan 2020 00:00:00 GMT") == 0


def test_gate_and_publications_rollback_together(system):
    db, _, _ = system
    job = repair(db)
    db.update(job["id"], state="running", session_id="existing")
    reports = [
        {"key": "one", "payload": {"provider": "github", "body": "report"}},
        {"key": "two", "payload": {"not_json": {object()}}},
    ]
    with pytest.raises(TypeError):
        db.commit_validation(job["id"], "review_ready", {"gate": "review_ready"}, None, reports)
    assert db.get(job["id"])["state"] == "running"
    assert not db.publications()
    assert db.commit_validation(job["id"], "review_ready", {}, None, reports[:1])
    assert db.get(job["id"])["state"] == "review_ready"
    assert db.publications()[0]["key"] == "one"


def test_intake_replay_and_provider_probe_are_idempotent(system):
    from app.automation.inbox import Inbox

    db, _, e = system
    Inbox(e).accept("delivery-1", {"event": "issues", "number": 1})
    with db.connect() as c:
        c.execute("UPDATE github_inbox SET state='dead_letter'")
    intent = uuid4()
    receipt = replay(e, "inbox", "delivery-1", intent)
    assert replay(e, "inbox", "delivery-1", intent) == receipt
    with pytest.raises(HTTPException):
        replay(e, "inbox", "delivery-1", uuid4())
    with pytest.raises(HTTPException):
        replay(e, "provider", "unconfigured", uuid4())
    assert Recovery(db).overview()["inbox"][0]["state"] == "pending"


def test_storage_outage_retries_existing_session_without_paid_reexecution(system, monkeypatch):
    db, p, e = system
    job = repair(db)
    e.tick()
    due(db)
    monkeypatch.setattr(e, "poll", lambda job: (_ for _ in ()).throw(OSError("disk full")))
    e.tick()
    assert db.get(job["id"])["state"] == "running"
    assert Recovery(db).record("job:" + job["id"])["category"] == "storage"
    assert p.created == 1


def test_credit_rejection_requires_operator_recovery(system):
    db, p, e = system
    job = repair(db)
    p.failure = ProviderError("credits unavailable", 402)
    e.tick()
    assert db.get(job["id"])["state"] == "blocked"
    assert Recovery(db).record("job:" + job["id"])["category"] == "credits"
    e.tick()
    assert p.created == 1
