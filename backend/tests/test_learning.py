import copy
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.learning import LearningService, workflow_lane
from app.automation.patches import PatchService, eligible_patch
from app.automation.providers import ProviderError, UnknownEffect
from app.automation.store import Store
from test_automation import SHA, FakeProvider


class KnowledgeProvider(FakeProvider):
    def __init__(self, settings):
        self.settings = settings
        self.notes = {}
        self.posts = 0
        self.uncertain = False
        self.read_failure = False
        self.post_failure = False
        self.payloads = []

    def devin(self, method, path, **kwargs):
        if method == "PUT":
            assert {"name", "body", "trigger"} <= kwargs["json"].keys()
            note = self.notes[path.rsplit("/", 1)[-1]]
            note.update(kwargs["json"])
            return note
        if method == "POST":
            if self.post_failure:
                raise ProviderError("Denied", 403)
            self.posts += 1
            note = {**kwargs["json"], "org_id": self.settings.org, "note_id": f"note-{self.posts}"}
            self.notes[note["note_id"]] = note
            if self.uncertain:
                raise UnknownEffect("lost response")
            return note
        if path == "knowledge/notes":
            return {"items": list(self.notes.values()), "has_next_page": False}
        if self.read_failure:
            raise ProviderError("Read failed")
        return self.notes[path.rsplit("/", 1)[-1]]

    def create_session(self, payload):
        self.payloads.append(copy.deepcopy(payload))
        return super().create_session(payload)


@pytest.fixture
def setup(tmp_path):
    s = replace(
        Settings(),
        database=str(tmp_path / "jobs.db"),
        enabled=True,
        devin_key="test",
        github_token="test",
    )
    db = Store(s.database)
    p = KnowledgeProvider(s)
    return db, p, Engine(s, db, p), LearningService(s, db, p)


def observation(db, kind="repair", state="implemented"):
    job = db.enqueue(
        "source", kind, {"title": "Fix date grain", "base_sha": SHA}, candidate_sha=SHA, pr_number=2
    )
    db.update(
        job["id"],
        state=state,
        result={
            "summary": "Fixed, according to implementation session",
            "tests": ["pytest regression"],
        },
        session_url="https://app.devin.ai/sessions/source",
    )
    return db.get(job["id"])


def test_native_write_readback_and_exact_dispatch_snapshot(setup):
    db, p, engine, learning = setup
    observation(db)
    learning.sync()
    lesson = learning.lessons()[0]
    assert lesson["native_state"] == "confirmed"
    assert lesson["observation"]["status"] == "reported"
    job = db.enqueue("scan", "scan", {"base_sha": SHA})
    engine.dispatch(job)
    assert p.payloads[0]["knowledge_ids"] == [lesson["note_id"]]
    snapshot = learning.context(job)
    db.update(lesson["job_id"], result={"summary": "later change"})
    learning.sync()
    assert learning.context(job) == snapshot
    assert len(learning.overview()["contexts"]) == 1


def test_unknown_create_reconciles_without_duplicate(setup):
    db, p, _, learning = setup
    observation(db)
    p.uncertain = True
    learning.sync()
    assert learning.lessons()[0]["native_state"] == "unknown_effect"
    learning.sync()
    assert p.posts == 1 and learning.lessons()[0]["native_state"] == "confirmed"


def test_unknown_write_absent_from_search_is_never_repeated(setup):
    db, p, _, learning = setup
    observation(db)
    p.uncertain = True
    learning.sync()
    p.notes.clear()
    learning.sync()
    assert p.posts == 1
    assert learning.lessons()[0]["native_state"] == "unknown_effect"


def test_receipt_survives_readback_outage(setup):
    db, p, _, learning = setup
    observation(db)
    p.read_failure = True
    learning.sync()
    assert learning.lessons()[0]["native_state"] == "receipt"
    p.read_failure = False
    learning.sync()
    assert p.posts == 1 and learning.lessons()[0]["native_state"] == "confirmed"


def test_definitive_permission_failure_can_recover(setup):
    db, p, _, learning = setup
    observation(db)
    p.post_failure = True
    learning.sync()
    assert learning.lessons()[0]["native_state"] == "pending"
    p.post_failure = False
    learning.sync()
    assert learning.lessons()[0]["native_state"] == "confirmed"


@pytest.mark.parametrize(
    "change",
    [
        {"org_id": "other"},
        {"pinned_repo": "https://github.com/apache/superset"},
        {"is_enabled": False},
        {"body": "changed"},
    ],
)
def test_changed_or_wrong_scope_note_not_supplied(setup, change):
    db, p, _, learning = setup
    observation(db)
    learning.sync()
    next(iter(p.notes.values())).update(change)
    job = db.enqueue("next", "scan", {"base_sha": SHA})
    assert learning.context(job)[0]["knowledge_id"] is None


def test_failed_and_stale_never_promoted_to_verified(setup):
    db, p, _, learning = setup
    source = observation(db, "validation", "validation_failed")
    learning.sync()
    assert learning.lessons()[0]["observation"]["status"] == "validation_failed"
    assert learning.overview()["cohorts"][0]["failed"] == 1
    db.update(source["id"], state="stale")
    learning.capture()
    next_job = db.enqueue("next", "scan", {"base_sha": SHA})
    assert learning.context(next_job) == []
    assert learning.overview()["cohorts"] == []


def test_disabled_native_learning_still_records_local_context(setup):
    db, p, engine, _ = setup
    observation(db)
    learning = LearningService(replace(engine.settings, learning_enabled=False), db, p)
    learning.sync()
    job = db.enqueue("next", "scan", {"base_sha": SHA})
    assert learning.context(job)[0]["knowledge_id"] is None
    assert p.posts == 0


def test_scan_retry_after_issue_created_ensures_child_and_lineage(setup):
    db, p, engine, _ = setup
    scan = db.enqueue("scan", "scan", {"base_sha": SHA})
    finding = {
        "base_sha": SHA,
        "title": "broken",
        "description": "problem",
        "reproduction": "failed test",
        "acceptance": "regression passes",
    }
    import hashlib

    key = "finding:" + hashlib.sha256((engine.settings.repo + "broken").encode()).hexdigest()[:20]
    db.remember(key, {"issue": 7, "sha": SHA})
    # Webhook wins the race; scan completion must reconcile its existing repair.
    child = db.enqueue(f"issue:{engine.settings.repo}:7", "repair", {"source": "github_webhook"})
    engine.finish_scan(scan, {"findings": [finding], "summary": "Found one defect"})
    child = db.get(child["id"])
    assert child["parent_id"] == scan["id"]
    assert workflow_lane(child, db) == "Autonomous patches and fixes"
    assert db.get(scan["id"])["result"]["findings"] == [finding]
    engine.finish_scan(scan, {"findings": [finding]})
    assert len(db.operational_jobs()) == 2


def patch_pr(settings):
    return {
        "number": 8,
        "title": "Fix bug",
        "state": "open",
        "draft": False,
        "user": {"login": settings.allowed_actor},
        "labels": [{"name": settings.label}],
        "html_url": f"https://github.com/{settings.repo}/pull/8",
        "base": {"repo": {"full_name": settings.repo}, "ref": settings.branch, "sha": "b" * 40},
        "head": {"repo": {"full_name": settings.repo}, "ref": "fix/bug", "sha": SHA},
    }


def test_patch_reuses_original_pr_and_queues_independent_validation(setup):
    db, p, engine, _ = setup
    pr = patch_pr(engine.settings)
    p.pr = lambda number: pr
    service = PatchService(engine.settings, db, p)
    job = service.accept(8, "patch_webhook")
    assert service.accept(8, "patch_poll")["id"] == job["id"]
    engine.dispatch(job)
    assert "existing patch PR #8" in p.payloads[-1]["prompt"]
    service.finish(
        db.get(job["id"]), {"candidate_sha": SHA, "pr_url": pr["html_url"], "summary": "prepared"}
    )
    validations = [j for j in db.operational_jobs() if j["kind"] == "validation"]
    assert len(validations) == 1
    assert validations[0]["parent_id"] == job["id"]
    assert validations[0]["payload"]["work_type"] == "patch"


def test_patch_requires_owner_label_fork_and_non_release_head(setup):
    _, _, engine, _ = setup
    pr = patch_pr(engine.settings)
    for bad in [
        {"labels": []},
        {"user": {"login": "stranger"}},
        {"head": {**pr["head"], "repo": {"full_name": "apache/superset"}}},
        {"head": {**pr["head"], "ref": engine.settings.branch}},
    ]:
        with pytest.raises(ValueError):
            eligible_patch(engine.settings, {**pr, **bad})


def test_lanes_and_learning_views_do_not_bypass_attention_hold(setup):
    db, p, engine, learning = setup
    held = observation(db)
    db.update(held["id"], state="needs_attention")
    job = db.enqueue("next", "scan", {"base_sha": SHA})
    learning.overview()
    workflow_lane(job, db)
    assert engine.tick() is None
    assert not p.payloads


def test_stale_and_disabled_native_notes_are_retired_with_readback(setup):
    db, p, engine, learning = setup
    source = observation(db, "validation", "review_ready")
    learning.sync()
    note = next(iter(p.notes.values()))
    assert note["is_enabled"] is True
    note["folder_id"] = "folder-retain"
    original = {k: note[k] for k in ("name", "body", "trigger", "pinned_repo", "folder_id")}
    db.update(source["id"], state="stale")
    learning.sync()
    assert note["is_enabled"] is False
    assert {k: note[k] for k in original} == original
    assert learning.lessons()[-1]["native_state"] == "retired"
    db.update(source["id"], state="review_ready")
    learning.sync()
    disabled = LearningService(replace(engine.settings, learning_enabled=False), db, p)
    disabled.sync()
    assert all(n["is_enabled"] is False for n in p.notes.values())


def test_managed_repair_pr_does_not_start_second_patch_pipeline(setup):
    db, p, engine, _ = setup
    managed = observation(db)
    p.pr = lambda number: patch_pr(engine.settings)
    service = PatchService(engine.settings, db, p)
    assert service.accept(2, "patch_poll")["id"] == managed["id"]
    db.update(managed["id"], state="running", pr_number=None)
    with pytest.raises(ValueError, match="handoff pending"):
        service.accept(8, "patch_webhook")
    assert len(db.operational_jobs()) == 1


def test_unknown_note_retirement_never_becomes_phantom_paid_session(setup):
    db, p, engine, learning = setup
    source = observation(db, "validation", "review_ready")
    learning.sync()
    db.update(source["id"], state="stale")
    job = db.enqueue("next", "scan", {"base_sha": SHA})
    original = p.devin

    def uncertain_put(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if method == "PUT":
            raise UnknownEffect("retirement applied; response lost")
        return result

    p.devin = uncertain_put
    engine.tick()
    assert db.get(job["id"])["state"] == "queued"
    assert db.session_count(excluding="") == 0
    assert not p.payloads
    p.devin = original
    learning.sync()
    db.update(job["id"], next_poll=0)
    engine.tick()
    assert db.get(job["id"])["state"] == "running"
    assert len(p.payloads) == 1


def test_patch_dispatch_rechecks_ownership_after_late_handoff(setup):
    db, p, engine, _ = setup
    p.pr = lambda number: patch_pr(engine.settings)
    service = PatchService(engine.settings, db, p)
    patch = service.accept(8, "patch_poll")
    repair = observation(db)
    db.update(repair["id"], pr_number=8)
    engine.dispatch(patch)
    assert db.get(patch["id"])["state"] == "blocked"
    assert not p.payloads
    db.update(repair["id"], state="needs_attention", pr_number=None)
    with pytest.raises(ValueError, match="handoff pending"):
        service.accept(8, "patch_poll")
