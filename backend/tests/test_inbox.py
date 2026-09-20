"""Failure injection for durable webhook intake; no paid provider mutations."""

from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.inbox import Inbox
from app.automation.providers import ProviderError, UnknownEffect
from app.automation.resilience import Recovery
from app.automation.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "inbox.db")
    engine = Engine(replace(Settings(), database=store.path), store, None)
    calls = []

    def accept_issue(number, source):
        calls.append(number)
        return store.enqueue(f"issue:{number}", "repair", {"issue_number": number})

    engine.accept_issue = accept_issue
    return store, engine, calls


def make_due(store):
    with store.connect() as c:
        c.execute("UPDATE github_inbox SET next_retry=0,lease_until=0")


def test_restart_preserves_normalized_delivery_without_provider_access(setup):
    store, engine, calls = setup
    inbox = Inbox(engine)
    payload = {"event": "issues", "number": 42}
    assert inbox.accept("delivery", payload)["status"] == "queued"
    assert not calls and not store.jobs()
    restarted = Inbox(Engine(engine.settings, Store(store.path), None))
    restarted.engine.accept_issue = engine.accept_issue
    assert restarted.accept("delivery", payload)["status"] == "duplicate"
    assert restarted.tick()["state"] == "completed"
    assert restarted.tick() is None
    assert calls == [42] and len(store.jobs()) == 1


def test_interrupted_claim_is_reclaimed_without_duplicate_job(setup):
    store, engine, calls = setup
    inbox = Inbox(engine)
    inbox.accept("delivery", {"event": "issues", "number": 42})
    claimed = inbox.claim()
    assert inbox.tick() is None
    # Simulate process dying after idempotent job creation, before inbox completion.
    inbox.process(claimed)
    make_due(store)
    assert Inbox(engine).tick()["state"] == "completed"
    assert calls == [42] and len(store.jobs()) == 1


def test_transient_read_failures_backoff_then_dead_letter(setup):
    store, engine, calls = setup
    inbox = Inbox(engine)
    inbox.accept("delivery", {"event": "issues", "number": 42})

    def fail(*args):
        raise ProviderError("GitHub unavailable", 503)

    engine.accept_issue = fail
    for attempt in range(1, 6):
        assert inbox.tick()["state"] == ("dead_letter" if attempt == 5 else "pending")
        record = Recovery(store).record("inbox:delivery")
        assert record["attempts"] == attempt and record["next_retry"] > 0
        assert inbox.tick() is None
        make_due(store)
    assert not store.jobs() and not calls
    assert Inbox(engine).tick() is None


@pytest.mark.parametrize(
    "failure,state",
    [
        (ProviderError("Token expired", 401), "blocked"),
        (UnknownEffect("Ambiguous outcome"), "unknown_effect"),
        (ValueError("Issue author is not authorized"), "ignored"),
    ],
)
def test_holds_and_invalid_events_are_not_blindly_replayed(setup, failure, state):
    store, engine, _ = setup
    inbox = Inbox(engine)
    inbox.accept("delivery", {"event": "issues", "number": 42})

    def fail(*args):
        raise failure

    engine.accept_issue = fail
    assert inbox.tick()["state"] == state
    make_due(store)
    assert inbox.tick() is None and not store.jobs()
    if state == "blocked":
        assert Recovery(store).record("inbox:delivery")["attempts"] == 0


def test_concurrent_claims_have_single_owner_and_delivery_payload_is_immutable(setup):
    from concurrent.futures import ThreadPoolExecutor

    store, engine, _ = setup
    inbox = Inbox(engine)
    inbox.accept("delivery", {"event": "issues", "number": 42})
    assert inbox.accept("delivery", {"event": "issues", "number": 99})["status"] == "duplicate"
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: Inbox(engine).claim(), range(2)))
    claimed = [item for item in claims if item]
    assert len(claimed) == 1 and claimed[0]["payload"]["number"] == 42
