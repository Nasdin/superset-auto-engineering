"""Bounded automatic failures, independent evidence and provider mutation durability."""

import copy
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.handoffs import HandoffRecovery
from app.automation.outbox import PublicationOutbox
from app.automation.providers import UnknownEffect
from app.automation.readiness import ci_status
from app.automation.remediation import RemediationService
from app.automation.store import Store
from test_automation import SHA, FakeProvider, result, validation

NEW = "b" * 40


class Provider(FakeProvider):
    def __init__(self):
        self.document = super().pr(2)
        self.document.update(title="Integrated repair", draft=True)
        self.checks = [{"name": "regression", "status": "completed", "conclusion": "success"}]
        self.required = []
        self.messages, self.comments = [], []
        self.ready_calls = self.created = 0
        self.response = {}

    def pr(self, number):
        return copy.deepcopy(self.document)

    def gh(self, method, path, **kwargs):
        if path.endswith("/check-runs"):
            return {"check_runs": self.checks}
        if path.endswith("required_status_checks"):
            return {"contexts": self.required}
        return super().gh(method, path, **kwargs)

    def devin(self, method, path, **kwargs):
        self.messages.append(kwargs["json"])
        if getattr(self, "message_failure", None):
            raise self.message_failure
        return {"session_id": path.split("/")[1]}

    def mark_ready(self, number, sha):
        self.ready_calls += 1
        self.document["draft"] = False
        if getattr(self, "ready_failure", None):
            raise self.ready_failure
        return {"number": number, "sha": sha}


@pytest.fixture
def system(tmp_path):
    db = Store(tmp_path / "recovery.db")
    settings = replace(
        Settings(),
        branch="master",
        enabled=True,
        devin_key="test",
        github_token="test",
        learning_enabled=False,
        max_sessions=20,
        max_acu=20,
    )
    p = Provider()
    engine = Engine(settings, db, p)
    return db, p, engine, RemediationService(settings, db, p)


def fail(engine, db, *, evidence=False):
    job = validation(db)
    handoff = result()
    if evidence:
        handoff["artifacts"] = [a for a in handoff["artifacts"] if a["kind"] != "video"]
    else:
        handoff["passed"] = False
        next(c for c in handoff["checks"] if c["name"] == "regression")["passed"] = False
    engine.finish_validation(job, handoff)
    return db.get(job["id"])


def test_failure_queues_one_repair_for_draft_integration_preserving_history(system):
    db, p, e, service = system
    job = fail(e, db)
    child = db.by_key("recovery:" + job["id"])
    assert child["kind"] == "remediation"
    assert child["payload"]["head_ref"] == p.document["head"]["ref"]
    assert child["payload"]["recovery_attempt"] == 1
    service.reconcile()
    assert len([j for j in db.jobs() if j["kind"] == "remediation"]) == 1
    assert job["state"] == "validation_failed"
    assert job["result"]["recovery"]["automatic"] is True


def test_failure_rolls_back_followup_and_publication_together(system, monkeypatch):
    db, p, e, service = system
    job = validation(db)
    before = len(db.jobs())
    handoff = result()
    handoff["passed"] = False

    def broken(*args, **kwargs):
        raise RuntimeError("disk")

    monkeypatch.setattr(db, "_queue_publication", broken)
    with pytest.raises(RuntimeError):
        e.finish_validation(job, handoff)
    assert len(db.jobs()) == before
    assert db.get(job["id"])["state"] == job["state"]
    assert db.all_publications() == []


def test_evidence_gap_creates_read_only_validator_not_code_repair(system):
    db, p, e, service = system
    job = fail(e, db, evidence=True)
    child = db.by_key("recovery:" + job["id"])
    assert child["kind"] == "validation" and child["candidate_sha"] == SHA
    from app.automation.prompts import session_payload

    prompt = session_payload(e.settings, child, [])["prompt"]
    assert "Do not edit code or tests, push commits" in prompt
    assert "collect the missing measurements or attachments yourself" in prompt


def test_repair_requires_new_same_branch_sha_then_fresh_independent_validator(system):
    db, p, e, service = system
    failed = fail(e, db)
    child = db.by_key("recovery:" + failed["id"])
    db.update(
        child["id"],
        session_id="repair-session",
        session_url="https://app.devin.ai/sessions/repair-session",
        state="running",
    )
    child = db.get(child["id"])
    final = {
        "task_complete": True,
        "pr_url": p.document["html_url"],
        "candidate_sha": SHA,
        "tests": ["regression"],
        "blocker": "",
    }
    with pytest.raises(ValueError, match="Unchanged SHA"):
        service.finish(child, final)
    p.document["head"]["sha"] = NEW
    final["candidate_sha"] = NEW
    service.finish(child, final)
    service.finish(child, final)
    fresh = [j for j in db.jobs() if j["kind"] == "validation" and j["candidate_sha"] == NEW]
    assert len(fresh) == 1 and child["id"] in fresh[0]["payload"]["implementation_jobs"]
    assert fresh[0]["session_id"] is None
    assert db.get(failed["id"])["state"] == "stale"
    assert db.get(failed["id"])["result"]["gate"] == "validation_failed"


def test_attempt_limit_preserves_budget_ceiling(system):
    db, p, e, service = system
    job = validation(db)
    job["payload"]["recovery_attempt"] = e.settings.max_remediation_attempts
    assert service.followups(job, result()) == []
    assert e.settings.max_sessions == 20 and e.settings.max_acu == 20


def test_ci_failure_blocks_good_evidence_and_queues_repair(system):
    db, p, e, service = system
    p.checks[0]["conclusion"] = "failure"
    job = validation(db)
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "validation_failed"
    assert db.by_key("recovery:" + job["id"])["kind"] == "remediation"
    assert all(not x["key"].startswith("github-ready:") for x in db.all_publications())


def test_disabling_auto_repairs_does_not_disable_ci_gate(system):
    db, p, e, service = system
    e.settings = replace(e.settings, autonomous_remediation=False)
    p.checks[0]["conclusion"] = "failure"
    job = validation(db)
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "validation_failed"
    assert db.by_key("recovery:" + job["id"]) is None


def test_pending_required_check_waits_then_marks_ready_once(system, monkeypatch):
    db, p, e, service = system
    p.required = ["missing-required"]
    job = validation(db)
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "awaiting_ci"
    assert db.by_key("recovery:" + job["id"]) is None
    original = p.attachments

    def no_download(*args):
        raise AssertionError("unchanged CI must not recollect attachments")

    monkeypatch.setattr(p, "attachments", no_download)
    service.reconcile()
    monkeypatch.setattr(p, "attachments", original)
    p.required = []
    service.reconcile()
    assert db.get(job["id"])["state"] == "review_ready"
    for _ in range(5):
        e.flush_publication()
    assert p.ready_calls == 1 and not p.document["draft"]


def test_later_ci_failure_on_review_ready_revision_queues_repair(system):
    db, p, e, service = system
    job = validation(db)
    e.finish_validation(job, result())
    p.checks[0]["conclusion"] = "failure"
    service.reconcile()
    assert db.get(job["id"])["state"] == "validation_failed"
    assert db.by_key("recovery:" + job["id"])["kind"] == "remediation"


def test_ambiguous_ready_mutation_reconciles_without_resending(system):
    db, p, e, service = system
    job = validation(db)
    e.finish_validation(job, result())
    p.ready_failure = UnknownEffect("lost response")
    for _ in range(4):
        e.flush_publication()
    ready = next(x for x in db.all_publications() if x["key"].startswith("github-ready:"))
    assert ready["state"] == "unknown_effect"
    PublicationOutbox(e.settings, db, p).reconcile_readiness()
    assert p.ready_calls == 1
    assert next(x for x in db.all_publications() if x["key"] == ready["key"])["state"] == "sent"


def paused(db, p, *, status="running", detail="finished", complete=True):
    job = db.enqueue("paused", "dependency", {})
    db.update(
        job["id"],
        state="needs_attention",
        session_id="paused",
        session_url="https://app.devin.ai/sessions/paused",
    )
    p.response = {
        "status": status,
        "status_detail": detail,
        "tags": ["cognition-job:" + job["id"]],
        "structured_output": {
            "task_complete": complete,
            "blocker": "None. Minor gaps: screenshot absent",
        },
    }
    return db.get(job["id"])


def test_one_automatic_correction_then_conclusive_failure_releases_queue(system):
    db, p, e, service = system
    job = paused(db, p)
    recovery = HandoffRecovery(e)
    recovery.tick()
    assert db.get(job["id"])["state"] == "running" and len(p.messages) == 1
    assert "Do not write 'None'" in p.messages[0]["message"]
    db.update(job["id"], state="needs_attention")
    recovery.tick()
    assert (
        db.get(job["id"])["state"] == "needs_attention"
    )  # Old final snapshot is not a new completion.
    p.response["structured_output"]["summary"] = "Correction attempted; the blocker persists."
    p.response["status_detail"] = "waiting_for_user"
    recovery.tick()
    assert db.get(job["id"])["state"] == "failed" and len(p.messages) == 1
    assert db.metrics()["attention"] == 1
    db.enqueue("next", "scan", {})
    assert db.claim() is not None


@pytest.mark.parametrize(
    "status,detail,complete",
    [
        ("running", "working", True),
        ("suspended", "usage_limit_exceeded", True),
        ("running", "waiting_for_approval", True),
        ("running", "finished", False),
    ],
)
def test_live_credit_approval_or_incomplete_handoffs_not_released(system, status, detail, complete):
    db, p, e, service = system
    job = paused(db, p, status=status, detail=detail, complete=complete)
    db.remember("handoff-followup:" + job["id"], {"attempts": 1})
    HandoffRecovery(e).tick()
    assert db.get(job["id"])["state"] == "needs_attention" and not p.messages


def test_inactivity_suspension_gets_followup_not_terminalized(system):
    db, p, e, service = system
    job = paused(db, p, status="suspended", detail="inactivity")
    HandoffRecovery(e).tick()
    assert len(p.messages) == 1 and db.get(job["id"])["state"] == "running"


def test_uncertain_followup_never_retries(system):
    db, p, e, service = system
    job = paused(db, p)
    p.message_failure = UnknownEffect("lost reply")
    recovery = HandoffRecovery(e)
    recovery.tick()
    recovery.tick()
    assert len(p.messages) == 1 and db.get(job["id"])["state"] == "unknown_effect"


def test_repair_and_validation_are_prioritized_before_new_scans(system):
    db, p, e, service = system
    db.enqueue("old-scan", "scan", {})
    db.enqueue("validator", "validation", {})
    repair = db.enqueue("repair", "remediation", {})
    assert db.claim()["id"] == repair["id"]


def test_readiness_rejects_stale_and_cross_fork_heads(system):
    db, p, e, service = system
    p.document["head"]["sha"] = NEW
    with pytest.raises(ValueError):
        ci_status(e.settings, p, 2, SHA)
    p.document["head"]["sha"] = SHA
    p.document["head"]["repo"]["full_name"] = "apache/superset"
    with pytest.raises(ValueError):
        ci_status(e.settings, p, 2, SHA)


def test_metadata_only_same_sha_requires_fresh_green_ci_then_new_validator(system):
    db, p, e, service = system
    p.checks[0]["conclusion"] = "failure"
    job = validation(db)
    e.finish_validation(job, result())
    child = db.by_key("recovery:" + job["id"])
    db.update(
        child["id"],
        session_id="metadata-repair",
        session_url="https://app.devin.ai/sessions/metadata-repair",
        state="running",
    )
    child = db.get(child["id"])
    handoff = {
        "task_complete": True,
        "pr_url": p.document["html_url"],
        "candidate_sha": SHA,
        "metadata_only": True,
        "blocker": "",
        "tests": ["PR title check"],
    }
    with pytest.raises(ValueError, match="newly passing CI"):
        service.finish(child, handoff)
    p.checks[0]["conclusion"] = "success"
    service.finish(child, handoff)
    fresh = [j for j in db.jobs() if j["kind"] == "validation" and j["parent_id"] == child["id"]]
    assert len(fresh) == 1 and fresh[0]["candidate_sha"] == SHA
    assert fresh[0]["session_id"] is None


def test_ci_preflight_failure_queues_repair_without_creating_paid_validator(system):
    db, p, e, service = system
    p.checks[0]["conclusion"] = "failure"
    job = validation(db)
    db.update(job["id"], state="queued", session_id=None)
    e.tick()
    assert p.created == 0
    assert db.get(job["id"])["state"] == "validation_failed"
    assert db.get(job["id"])["result"]["provenance"] == "github_ci_preflight"
    assert db.by_key("recovery:" + job["id"])["kind"] == "remediation"


def test_repair_handoff_supersedes_old_gate_without_duplicate_validator(system):
    db, p, e, service = system
    old = fail(e, db)
    child = db.by_key("recovery:" + old["id"])
    db.update(
        child["id"],
        state="running",
        session_id="repair",
        session_url="https://app.devin.ai/sessions/repair",
    )
    p.document["head"]["sha"] = NEW
    service.finish(
        db.get(child["id"]),
        {
            "task_complete": True,
            "candidate_sha": NEW,
            "pr_url": p.document["html_url"],
            "blocker": "",
            "metadata_only": False,
        },
    )
    service.reconcile()
    e.refresh_readiness()
    assert (
        len([j for j in db.jobs() if j["kind"] == "validation" and j["candidate_sha"] == NEW]) == 1
    )
    assert db.get(old["id"])["state"] == "stale"


def test_malformed_ci_cannot_be_treated_as_success(system):
    db, p, e, service = system
    p.gh = lambda *args, **kwargs: {}
    from app.automation.providers import ProviderError

    with pytest.raises(ProviderError, match="incomplete"):
        ci_status(e.settings, p, 2, SHA)


def test_poll_cannot_accept_pre_followup_completed_handoff(system):
    db, p, e, service = system
    job = paused(db, p)
    HandoffRecovery(e).tick()
    p.response["updated_at"] = 9999999999  # Receipt timestamp alone is not completed work.
    e.poll(db.get(job["id"]))
    assert db.get(job["id"])["state"] == "running"
    assert len(p.messages) == 1


def mismatched_attachment_handoff(db, provider):
    """Simulate a provider-owned index whose URLs differ from the agent's final claims."""
    job = validation(db)
    canonical = {**result(), "task_complete": True}
    handoff = copy.deepcopy(canonical)
    for artifact in handoff["artifacts"]:
        artifact["url"] = artifact["url"].replace(
            "attachments.devin.ai/", "attachments.devin.ai/unconfirmed-"
        )
    for request in handoff["api_requests"]:
        request["evidence_url"] = request["evidence_url"].replace(
            "attachments.devin.ai/", "attachments.devin.ai/unconfirmed-"
        )
    for field in ("coverage", "test_results"):
        handoff[field]["report_url"] = handoff[field]["report_url"].replace(
            "attachments.devin.ai/", "attachments.devin.ai/unconfirmed-"
        )
    indexed = [
        {**item, "name": item["attachment_id"] + ".fixture"}
        for item in FakeProvider.attachments(provider, job["session_id"])
    ]
    provider.attachments = lambda session_id: copy.deepcopy(indexed)
    provider.response = {
        "status": "running",
        "status_detail": "finished",
        "tags": [f"cognition-job:{job['id']}"],
        "structured_output": copy.deepcopy(handoff),
    }
    return job, handoff, canonical


def test_attachment_reference_mismatch_requests_one_correction_without_filename_binding(system):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    held = db.get(job["id"])
    assert held["state"] == "needs_attention"
    assert held["result"]["handoff_correction"] == "attachment_references"
    assert held["result"]["artifacts"] == []
    assert db.by_key("recovery:" + job["id"]) is None
    assert db.publications() == []
    assert p.response["structured_output"] == handoff  # No fabricated URL substitution.
    HandoffRecovery(e).tick()
    assert db.get(job["id"])["state"] == "running"
    assert len(p.messages) == 1 and p.created == 0
    message = p.messages[0]["message"]
    assert "https://attachments.devin.ai/screenshot" in message
    assert "screenshot.fixture" in message
    assert "attachment" in message.lower() and (
        "mismatch" in message.lower() or "match" in message.lower()
    )
    HandoffRecovery(e).tick()
    assert len(p.messages) == 1


def test_attachment_correction_stale_handoff_is_rejected_after_restart(system):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    HandoffRecovery(e).tick()
    intent = db.recall("handoff-followup:" + job["id"])
    assert intent["original_handoff"] == HandoffRecovery.fingerprint(handoff)
    assert intent["requested_at"] > 0 and intent["attempts"] == 1
    restarted = Engine(e.settings, Store(db.path), p)
    p.response["updated_at"] = 9999999999  # Message receipt timestamp cannot approve stale output.
    restarted.poll(restarted.store.get(job["id"]))
    HandoffRecovery(restarted).tick()
    assert restarted.store.get(job["id"])["state"] == "running"
    assert len(p.messages) == 1 and p.created == 0
    assert restarted.store.publications() == []


def test_attachment_correction_unknown_delivery_persists_full_guard_and_never_resends(system):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    p.message_failure = UnknownEffect("simulated lost correction acknowledgement")
    HandoffRecovery(e).tick()
    assert db.get(job["id"])["state"] == "unknown_effect"
    intent = db.recall("handoff-followup:" + job["id"])
    assert intent["original_handoff"] == HandoffRecovery.fingerprint(handoff)
    assert intent["requested_at"] > 0
    restarted = Engine(e.settings, Store(db.path), p)
    HandoffRecovery(restarted).tick()
    assert len(p.messages) == 1 and p.created == 0
    assert restarted.store.get(job["id"])["state"] == "unknown_effect"


def test_agent_corrected_attachment_references_pass_ordinary_independent_gate(system):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    HandoffRecovery(e).tick()
    canonical["summary"] = (
        "Agent rechecked and corrected references from its actual session attachments"
    )
    p.response["structured_output"] = canonical
    e.poll(db.get(job["id"]))
    ready = db.get(job["id"])
    assert ready["state"] == "review_ready" and ready["result"]["gate_failures"] == []
    assert {a["url"] for a in ready["result"]["artifacts"]} == {
        a["url"] for a in canonical["artifacts"]
    }
    assert ready["session_id"] == job["session_id"]
    assert len(p.messages) == 1 and p.created == 0
    assert db.by_key("recovery:" + job["id"]) is None


def test_attachment_correction_still_invalid_after_one_followup_uses_normal_recollection(system):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    HandoffRecovery(e).tick()
    p.response["structured_output"]["summary"] = (
        "Agent attempted correction but still references missing attachment IDs"
    )
    e.poll(db.get(job["id"]))
    failed = db.get(job["id"])
    assert failed["state"] == "validation_failed"
    assert failed["result"]["gate_failures"]
    followup = db.by_key("recovery:" + job["id"])
    assert followup["kind"] == "validation" and followup["session_id"] is None
    HandoffRecovery(e).tick()
    assert len(p.messages) == 1 and p.created == 0


@pytest.mark.parametrize(
    "defect",
    ["missing_measurement", "wrong_sha", "failed_check", "legacy_schema", "missing_artifact_kind"],
)
def test_non_manifest_failures_never_qualify_for_reference_only_correction(system, defect):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    if defect == "missing_measurement":
        handoff.pop("coverage")
    elif defect == "wrong_sha":
        handoff["candidate_sha"] = NEW
    elif defect == "failed_check":
        next(c for c in handoff["checks"] if c["name"] == "regression")["passed"] = False
    elif defect == "legacy_schema":
        handoff.pop("evidence_version")
    else:
        handoff["artifacts"] = [a for a in handoff["artifacts"] if a["kind"] != "video"]
    e.finish_validation(job, handoff)
    observed = db.get(job["id"])
    assert observed["state"] == "validation_failed"
    assert observed["result"].get("handoff_correction") != "attachment_references"
    assert p.messages == []


@pytest.mark.parametrize("guard", ["archived", "credits", "approval", "working"])
def test_attachment_correction_does_not_message_non_quiescent_or_unavailable_sessions(
    system, guard
):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    e.finish_validation(job, handoff)
    if guard == "archived":
        p.response["is_archived"] = True
    elif guard == "credits":
        p.response.update(status="suspended", status_detail="usage_limit_exceeded")
    elif guard == "approval":
        p.response["status_detail"] = "waiting_for_approval"
    else:
        p.response["status_detail"] = "working"
    HandoffRecovery(e).tick()
    assert db.get(job["id"])["state"] == "needs_attention"
    assert p.messages == [] and p.created == 0


@pytest.mark.parametrize(
    "defect",
    [
        "truthy_complete",
        "truthy_pass",
        "blocker",
        "missing_owned_index",
        "unowned_index",
        "validator_is_implementer",
        "duplicate_claimed_url",
    ],
)
def test_attachment_reference_hold_requires_literal_finality_ownership_and_independence(
    system, defect
):
    db, p, e, service = system
    job, handoff, canonical = mismatched_attachment_handoff(db, p)
    if defect == "truthy_complete":
        handoff["task_complete"] = "true"
    elif defect == "truthy_pass":
        handoff["passed"] = 1
    elif defect == "blocker":
        handoff["blocker"] = "Runtime evidence remains incomplete"
    elif defect == "missing_owned_index":
        p.attachments = lambda session_id: []
    elif defect == "unowned_index":
        supplied = p.attachments(job["session_id"])
        p.attachments = lambda session_id: [{**item, "source": "user"} for item in supplied]
    elif defect == "validator_is_implementer":
        db.update(job["parent_id"], session_id=job["session_id"])
    else:
        handoff["artifacts"][1]["url"] = handoff["artifacts"][0]["url"]
    e.finish_validation(job, handoff)
    observed = db.get(job["id"])
    assert observed["state"] == "validation_failed"
    assert observed["result"].get("handoff_correction") != "attachment_references"
    assert p.messages == []
