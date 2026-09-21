import uuid

import pytest
from app.automation.feedback import FeedbackConflict, FeedbackService
from app.automation.learning_lock import learning_lease
from app.automation.routes import FeedbackRequest
from pydantic import ValidationError
from test_learning import observation

pytest_plugins = ["test_learning"]


def command(job, **changes):
    return FeedbackRequest(
        **{
            "request_id": str(uuid.uuid4()),
            "source_job_id": job["id"],
            "author": "Nasrudin (via Codex)",
            "title": "Failed tests cannot pass the gate",
            "reason": "The validator reported one failed test but marked regression passed.",
            "correction": "Report failure whenever any scoped regression test fails; preserve the actual counts.",
            **changes,
        }
    ).model_dump(mode="json")


def test_feedback_versions_are_idempotent_atomic_and_preserve_author(setup):
    db, p, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    receipt = service.save(first)
    assert service.save(first)["replayed"] is True
    with pytest.raises(FeedbackConflict):
        service.save({**first, "correction": "different"})
    revision = command(
        job,
        feedback_id=receipt["feedback_id"],
        expected_revision=receipt["id"],
        author="Another operator",
        correction="Also include the exact command",
    )
    service.save(revision)
    with pytest.raises(FeedbackConflict):
        service.save({**revision, "request_id": str(uuid.uuid4())})
    lessons = learning.lessons()
    assert len(lessons) == 2
    assert lessons[0]["observation"]["original_author"] == first["author"]
    assert lessons[0]["observation"]["author"] == "Another operator"
    assert lessons[1]["observation"]["summary"] == first["correction"]


def test_override_retires_original_and_native_revision_before_new_dispatch(setup):
    db, p, engine, learning = setup
    job = observation(db)
    learning.sync()
    source = learning.lessons()[0]
    service = FeedbackService(engine.settings, db)
    first = command(job, source_lesson_id=source["id"])
    service.save(first)
    learning.sync()
    assert not p.notes[source["note_id"]]["is_enabled"]
    feedback = next(lesson for lesson in learning.lessons() if lesson["id"] == first["request_id"])
    assert feedback["native_state"] == "confirmed"
    later = db.enqueue("later", "scan", {"base_sha": "a" * 40})
    engine.dispatch(later)
    memory = learning.context(later)
    assert [m["lesson_id"] for m in memory] == [feedback["id"]]
    assert p.payloads[-1]["knowledge_ids"] == [feedback["note_id"]]
    assert first["author"] in p.payloads[-1]["prompt"]
    revision = command(
        job,
        feedback_id=feedback["id"],
        expected_revision=feedback["id"],
        source_lesson_id=source["id"],
        retired=True,
    )
    service.save(revision)
    learning.sync()
    assert not p.notes[feedback["note_id"]]["is_enabled"]
    assert learning.context(later) == memory  # Historical confirmed session remains unchanged.
    assert learning.context(db.enqueue("new", "scan", {})) == []
    db.update(job["id"], result={"summary": "New agent report"})
    learning.capture()
    assert learning.context(db.enqueue("another", "scan", {})) == []


def test_source_capture_cannot_hide_parallel_feedback_streams(setup):
    db, _, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    ids = {service.save(command(job))["id"] for _ in range(2)}
    learning.capture()
    supplied = learning.context(db.enqueue("new", "scan", {}))
    assert ids <= {m["lesson_id"] for m in supplied}


def test_unsent_obsolete_snapshot_rebuilds_but_retains_history(setup):
    db, _, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    service.save(first)
    later = db.enqueue("new", "scan", {})
    before = learning.context(later)
    service.save(
        command(
            job,
            feedback_id=first["request_id"],
            expected_revision=first["request_id"],
            correction="Revised guidance",
        )
    )
    after = learning.context(later)
    assert after != before
    with db.connect() as c:
        assert len(c.execute("SELECT * FROM learning_context_history").fetchall()) == 1


def test_sync_lease_serializes_edits_and_uncertain_notes_reconcile(setup):
    db, p, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    with learning_lease(db):
        with pytest.raises(FeedbackConflict, match="sync is in progress"):
            service.save(first)
    service.save(first)
    p.uncertain = True
    learning.sync()
    posts = p.posts
    learning.sync()
    assert p.posts >= posts
    assert (
        next(lesson for lesson in learning.lessons() if lesson["id"] == first["request_id"])[
            "native_state"
        ]
        == "confirmed"
    )
    count = p.posts
    learning.sync()
    assert p.posts == count


def test_disable_readback_failure_prevents_paid_dispatch(setup):
    db, p, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    service.save(first)
    learning.sync()
    service.save(
        command(
            job,
            feedback_id=first["request_id"],
            expected_revision=first["request_id"],
            retired=True,
        )
    )
    p.read_failure = True
    later = db.enqueue("later", "scan", {})
    engine.dispatch(later)
    assert not p.payloads
    assert "Knowledge" in db.get(later["id"])["error"]


def test_source_mismatch_rejected_without_inserting_revision(setup):
    db, _, engine, learning = setup
    observation(db)
    learning.capture()
    other = db.enqueue("other", "scan", {})
    with pytest.raises(ValueError, match="belong"):
        FeedbackService(engine.settings, db).save(
            command(other, source_lesson_id=learning.lessons()[0]["id"])
        )
    assert len(learning.lessons()) == 1


@pytest.mark.parametrize(
    "field,value",
    [("author", " "), ("reason", ""), ("correction", "x" * 3001), ("source_job_id", "")],
)
def test_feedback_validation_bounds(field, value):
    with pytest.raises(ValidationError):
        command({"id": "job"}, **{field: value})


def test_head_wins_over_equal_or_reversed_timestamps(setup):
    db, _, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    service.save(first)
    second = command(job, feedback_id=first["request_id"], expected_revision=first["request_id"])
    service.save(second)
    with db.connect() as c:
        c.execute("UPDATE lessons SET created=1 WHERE id=:id", {"id": second["request_id"]})
    assert second["request_id"] in learning.active_ids()
    assert first["request_id"] not in learning.active_ids()
    context = learning.context(db.enqueue("later", "scan", {}))
    assert context[0]["lesson_id"] == second["request_id"]


def test_edit_during_context_readback_is_rejected_through_session_creation(setup):
    db, p, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    service.save(first)
    learning.sync()
    change = command(job, feedback_id=first["request_id"], expected_revision=first["request_id"])
    original = p.create_session

    def attempt(payload):
        with pytest.raises(FeedbackConflict):
            service.save(change)
        return original(payload)

    p.create_session = attempt
    engine.dispatch(db.enqueue("later", "scan", {"base_sha": "a" * 40}))
    assert len(p.payloads) == 1
    assert service.save(change)["id"] == change["request_id"]


def test_expired_lease_after_search_cannot_create_superseded_note(setup):
    db, p, engine, learning = setup
    job = observation(db)
    service = FeedbackService(engine.settings, db)
    first = command(job)
    service.save(first)
    original = p.devin

    def expire(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if path == "knowledge/notes" and method == "GET":
            with db.connect() as c:
                c.execute("UPDATE learning_guard SET expires=0")
        return result

    p.devin = expire
    learning.sync()
    assert p.posts == 0
    assert db.recall("learning_sync", {})["state"] == "attention"


def test_expired_lease_after_create_is_uncertain_not_safe_to_retry(setup):
    db, p, engine, learning = setup
    observation(db)
    original = p.devin

    def expire(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if method == "POST":
            with db.connect() as c:
                c.execute("UPDATE learning_guard SET expires=0")
        return result

    p.devin = expire
    learning.sync()
    assert learning.lessons()[0]["native_state"] == "unknown_effect"
    p.devin = original
    learning.sync()
    assert p.posts == 1
    assert learning.lessons()[0]["native_state"] == "confirmed"


def test_new_feedback_rebuilds_an_unsent_snapshot(setup):
    db, _, engine, learning = setup
    job = observation(db)
    later = db.enqueue("later", "scan", {})
    before = learning.context(later)
    receipt = FeedbackService(engine.settings, db).save(command(job))
    after = learning.context(later)
    assert after != before
    assert after[0]["lesson_id"] == receipt["id"]
    with db.connect() as c:
        assert len(c.execute("SELECT * FROM learning_context_history").fetchall()) == 1


def test_historical_gate_outcome_survives_candidate_supersession(setup):
    db, _, _, learning = setup
    job = observation(db, "validation", "running")
    db.commit_validation(job["id"], "validation_failed", {"gate": "validation_failed"}, "failed")
    before = learning.overview()["cohorts"]
    db.update(job["id"], state="stale")
    assert learning.overview()["cohorts"] == before
    assert before[0]["failed"] == 1


def test_discovery_prompt_requests_feedback_revision_attribution(setup):
    db, p, engine, learning = setup
    job = observation(db)
    feedback = FeedbackService(engine.settings, db).save(command(job))
    engine.dispatch(db.enqueue("later", "scan", {"base_sha": "a" * 40}))
    prompt = p.payloads[-1]["prompt"]
    assert feedback["id"] in prompt
    assert "which feedback revision you applied" in prompt
    assert "operator-reported author" in prompt
