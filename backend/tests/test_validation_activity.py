"""Simulated provider delivery of durable progress, never live execution."""

from dataclasses import replace

import pytest
from app.automation.activity import ValidationActivityService
from app.automation.config import Settings
from app.automation.outbox import PublicationOutbox
from app.automation.providers import ProviderError, UnknownEffect
from app.automation.store import Store
from test_automation import SHA, FakeProvider


class ActivityProvider(FakeProvider):
    def __init__(self):
        self.comments = []
        self.pr_reads = 0
        self.confirmations = 0
        self.head = SHA
        self.after_read = lambda: None
        self.uncertain = False
        self.confirm_error = False

    def pr(self, number):
        self.pr_reads += 1
        pr = super().pr(number)
        pr["head"]["sha"] = self.head
        self.after_read()
        return pr

    def comment(self, number, body, repository=None):
        receipt = super().comment(number, body, repository)
        if self.uncertain:
            raise UnknownEffect("Lost comment acknowledgement")
        return receipt

    def confirm_publication(self, payload, receipt):
        self.confirmations += 1
        if self.confirm_error:
            raise ProviderError("Readback unavailable")
        return super().confirm_publication(payload, receipt)


@pytest.fixture
def activity(tmp_path):
    store = Store(tmp_path / "activity.db")
    settings = replace(Settings(), branch="master", github_token="fixture")
    provider = ActivityProvider()
    job = store.enqueue("fixture-validator", "validation", {}, pr_number=6, candidate_sha=SHA)
    store.update(
        job["id"],
        state="running",
        session_id="validator-fixture",
        session_url="https://app.devin.ai/sessions/validator-fixture",
    )
    return store, settings, provider, job


def services(activity):
    store, settings, provider, _ = activity
    return ValidationActivityService(settings, store, provider), PublicationOutbox(
        settings, store, provider
    )


def test_restart_discovers_running_validator_and_posts_started_once(activity):
    store, settings, provider, job = activity
    service, outbox = services(activity)
    service.tick()
    assert provider.pr_reads == 0 and provider.comments == []
    # Reconstruct the service/store exactly as a worker restart would.
    reopened = Store(store.path)
    ValidationActivityService(settings, reopened, provider).tick()
    assert len(store.all_publications()) == 1
    outbox.flush_publication()
    service.tick()
    outbox.flush_publication()
    assert len(provider.comments) == 1
    number, body = provider.comments[0]
    assert number == 6 and SHA in body
    assert "https://app.devin.ai/sessions/validator-fixture" in body
    assert "not approval or a passing release gate" in body
    assert store.all_publications()[0]["state"] == "sent"
    assert store.get(job["id"])["state"] == "running"


@pytest.mark.parametrize("change", ["final", "head", "session", "sha", "during_read"])
def test_undelivered_activity_is_discarded_if_its_execution_is_no_longer_current(activity, change):
    store, _, provider, job = activity
    service, outbox = services(activity)
    service.tick()
    if change == "final":
        store.update(job["id"], state="review_ready")
    elif change == "head":
        provider.head = "b" * 40
    elif change == "session":
        store.update(job["id"], session_id="another-validator")
    elif change == "sha":
        store.update(job["id"], candidate_sha="b" * 40)
    else:
        provider.after_read = lambda: store.update(job["id"], state="validation_failed")
    outbox.flush_publication()
    assert not provider.comments
    assert store.all_publications()[0]["state"] == "stale"


def test_acknowledged_comment_only_retries_confirmation_after_completion(activity):
    store, _, provider, job = activity
    service, outbox = services(activity)
    service.tick()
    provider.confirm_error = True
    outbox.flush_publication()
    assert len(provider.comments) == 1
    assert store.all_publications()[0]["state"] == "delivered"
    reads = provider.pr_reads
    store.update(job["id"], state="review_ready")
    provider.head = "b" * 40
    provider.confirm_error = False
    with store.connect() as connection:
        connection.execute("UPDATE recovery SET next_retry=0")
    services(activity)[1].flush_publication()
    assert provider.pr_reads == reads  # Receipt confirmation never re-runs mutation preflight.
    assert len(provider.comments) == 1 and provider.confirmations == 2
    assert store.all_publications()[0]["state"] == "sent"


def test_uncertain_comment_is_not_resent_after_restart(activity):
    store, settings, provider, _ = activity
    service, outbox = services(activity)
    service.tick()
    provider.uncertain = True
    outbox.flush_publication()
    assert store.all_publications()[0]["state"] == "unknown_effect"
    reopened = Store(store.path)
    ValidationActivityService(settings, reopened, provider).tick()
    PublicationOutbox(settings, reopened, provider).flush_publication()
    assert len(provider.comments) == 1 and provider.confirmations == 0


def test_safe_preflight_failure_retries_before_any_mutation(activity, monkeypatch):
    store, _, provider, _ = activity
    service, outbox = services(activity)
    service.tick()
    original = provider.pr

    def unavailable(_):
        raise ProviderError("GitHub read unavailable")

    monkeypatch.setattr(provider, "pr", unavailable)
    outbox.flush_publication()
    assert store.all_publications()[0]["state"] == "pending"
    assert not provider.comments
    monkeypatch.setattr(provider, "pr", original)
    with store.connect() as connection:
        connection.execute("UPDATE recovery SET next_retry=0")
    outbox.flush_publication()
    assert len(provider.comments) == 1


def test_nonrunning_or_nonvalidator_jobs_do_not_create_activity(activity):
    store, _, _, job = activity
    service, _ = services(activity)
    store.update(job["id"], state="awaiting_ci")
    other = store.enqueue("repair", "repair", {}, pr_number=7, candidate_sha=SHA)
    store.update(
        other["id"],
        state="running",
        session_id="repair",
        session_url="https://app.devin.ai/sessions/repair",
    )
    service.tick()
    assert store.all_publications() == []


def test_worker_reconciles_activity_even_when_new_paid_dispatch_is_disabled(activity):
    import time

    from app.automation.engine import Engine
    from app.automation.worker import cycle

    store, settings, provider, _ = activity
    store.remember("last_issue_poll", {"at": time.time()})
    engine = Engine(settings, store, provider)
    cycle(engine)
    assert store.all_publications()[0]["state"] == "pending"
    cycle(engine)
    assert store.all_publications()[0]["state"] == "sent"
    assert len(provider.comments) == 1
    assert not store.recall("worker_status")["failures"]
