from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from app.automation.catalogue import RECIPES, attributed_jobs
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.prompts import session_payload
from app.automation.reviews import finish_review
from app.automation.schedules import ScheduleConflict, ScheduleService
from app.automation.store import Store
from test_automation import FakeProvider
from test_schedules import client_for


@pytest.fixture
def setup(tmp_path):
    settings = replace(
        Settings(),
        database=str(tmp_path / "catalogue.db"),
        enabled=True,
        devin_key="test",
        github_token="test",
        operator_token="operator",
    )
    store = Store(settings.database)
    provider = FakeProvider()
    provider.gh = lambda *args, **kwargs: {"sha": "a" * 40}
    yield settings, store, provider, ScheduleService(settings, store, provider)
    store.database.close()


def test_new_recipes_are_paused_and_independently_configurable(setup):
    settings, store, provider, service = setup
    catalogue = service.overview()["catalogue"]
    assert len(catalogue) == 8
    assert [item["id"] for item in catalogue if item["enabled"]] == ["discovery"]
    first = service.schedule("code_patterns")
    saved = service.configure(True, 604800, first["updated"], "code_patterns")
    assert saved["next_run"] > first["updated"] + 604790
    assert service.schedule("owasp")["enabled"] == 0
    restarted = Store(settings.database)
    try:
        assert (
            ScheduleService(settings, restarted, provider).schedule("code_patterns")["enabled"] == 1
        )
    finally:
        restarted.database.close()
    with pytest.raises(ScheduleConflict):
        service.configure(False, 604800, first["updated"], "code_patterns")
    assert store.jobs() == []


def test_manual_automation_is_deduplicated_and_keeps_origin(setup):
    _, store, _, service = setup
    intent = str(uuid4())
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: service.run_now(intent, "code_patterns"), range(4)))
    assert len({job["id"] for job in jobs}) == 1
    assert jobs[0]["payload"]["automation_id"] == "code_patterns"
    assert jobs[0]["payload"]["source"] == "manual"
    with pytest.raises(ScheduleConflict):
        service.run_now(str(uuid4()), "code_patterns")
    other = service.run_now(str(uuid4()), "release_readiness")
    assert other["kind"] == "audit" and len(store.jobs()) == 2
    assert service.schedule("code_patterns")["enabled"] == 0


def test_recipes_coalesce_missed_ticks_without_cross_attribution(setup):
    _, store, _, service = setup
    discovery = service.schedule()
    service.configure(False, 86400, discovery["updated"])
    for identity in ["code_patterns", "owasp"]:
        row = service.schedule(identity)
        service.configure(True, 3600, row["updated"], identity)
    with store.connect() as c:
        c.execute("UPDATE schedules SET next_run=1")
    service.tick_all()
    first = store.jobs()
    assert len(first) == 2
    assert {j["payload"]["automation_id"] for j in first} == {"code_patterns", "owasp"}
    with store.connect() as c:
        c.execute("UPDATE schedules SET next_run=1 WHERE enabled=1")
    service.tick_all()
    assert len(store.jobs()) == 2


def test_cloudflare_requires_scoped_configuration_and_unknown_recipes_fail(setup):
    _, store, _, service = setup
    row = service.schedule("cloudflare_audit")
    with pytest.raises(ValueError, match="CLOUDFLARE"):
        service.configure(True, 604800, row["updated"], "cloudflare_audit")
    with pytest.raises(ScheduleConflict, match="CLOUDFLARE"):
        service.run_now(str(uuid4()), "cloudflare_audit")
    with pytest.raises(ValueError, match="Unknown"):
        service.run_now(str(uuid4()), "arbitrary-prompt")
    assert not store.jobs()


def test_source_follows_shared_integration_and_survives_missing_ancestor(setup):
    _, store, _, service = setup
    scans = [service.run_now(str(uuid4()), name) for name in ["code_patterns", "owasp"]]
    repairs = [store.enqueue(str(i), "repair", {}, parent_id=s["id"]) for i, s in enumerate(scans)]
    integration = store.enqueue(
        "integration", "integration", {"members": [{"job_id": r["id"]} for r in repairs]}
    )
    validation = store.enqueue(
        "validation",
        "validation",
        {"implementation_jobs": [r["id"] for r in repairs]},
        parent_id=repairs[0]["id"],
    )
    jobs = {j["id"]: j for j in attributed_jobs(store.operational_jobs())}
    for job in [integration, validation]:
        assert {a["id"] for a in jobs[job["id"]]["automations"]} == {"code_patterns", "owasp"}
    assert (
        attributed_jobs([{**validation, "payload": {}, "parent_id": "absent"}])[0]["automations"]
        == []
    )


@pytest.mark.parametrize("identity", list(RECIPES))
def test_recipe_payload_has_bounded_scope_and_native_correlation(setup, identity):
    settings, store, _, _ = setup
    settings = replace(
        settings, cloudflare_account_id="account", cloudflare_audit_secret_id="readonly-secret-id"
    )
    job = store.enqueue(
        identity, RECIPES[identity].kind, {"base_sha": "a" * 40, "automation_id": identity}
    )
    payload = session_payload(settings, job, [])
    assert f"cognition-automation:{identity}" in payload["tags"]
    assert payload["max_acu_limit"] == settings.max_acu
    assert settings.repo in payload["prompt"] and settings.branch in payload["prompt"]
    assert bool(payload.get("secret_ids")) == (identity == "cloudflare_audit")
    if identity == "code_patterns":
        assert "nearby maintained modules" in payload["prompt"]
    if RECIPES[identity].kind == "audit":
        assert "observations" in payload["structured_output_schema"]["required"]
        assert "Do not edit code" in payload["prompt"]


def test_audit_handoff_records_report_without_publication_and_retains_blocker(setup):
    _, store, _, service = setup
    job = service.run_now(str(uuid4()), "release_readiness")
    report = {
        "task_complete": True,
        "summary": "One redacted location needs review",
        "observations": ["config.py:5 rule credential"],
        "blocker": "",
    }
    finish_review(store, job, report)
    assert store.get(job["id"])["state"] == "completed"
    assert store.publications() == []
    assert len(store.jobs()) == 1
    finish_review(store, job, {**report, "blocker": "Scanner unavailable"})
    assert store.get(job["id"])["state"] == "needs_attention"
    with pytest.raises(ValueError):
        finish_review(store, job, {"summary": "pretend success"})


def test_limits_are_session_specific_and_do_not_claim_exhausted_org_credit(setup):
    settings, store, provider, service = setup
    job = service.run_now(str(uuid4()), "release_readiness")
    store.update(job["id"], state="running", session_id="test-session")
    provider.response = {"status": "suspended", "status_detail": "usage_limit_exceeded"}
    Engine(settings, store, provider).poll(store.get(job["id"]))
    assert "does not establish" in store.get(job["id"])["error"]
    assert store.recall("breaker:devin") is None
    provider.response = {"status": "suspended", "status_detail": "out_of_credits"}
    Engine(settings, store, provider).poll(store.get(job["id"]))
    assert store.recall("breaker:devin")["reason"] == "credits"


def test_catalogue_routes_require_operator_and_dispatch_permission(setup, tmp_path):
    settings, store, provider, service = setup
    client = client_for(settings, store, provider, tmp_path)
    row = service.schedule("code_patterns")
    body = {"enabled": True, "interval_seconds": 604800, "expected_updated": row["updated"]}
    assert client.post("/api/live/schedules/code_patterns", json=body).status_code == 401
    headers = {"Authorization": "Bearer operator", "X-Cognition-Intent": "session"}
    assert (
        client.post("/api/live/schedules/code_patterns", json=body, headers=headers).status_code
        == 200
    )
    url = "/api/live/automations/code_patterns/run"
    intent = {"request_id": str(uuid4())}
    assert client.post(url, json=intent).status_code == 401
    created = client.post(url, json=intent, headers=headers)
    assert created.status_code == 200
    assert client.post(url, json=intent, headers=headers).json()["id"] == created.json()["id"]
    assert (
        client.post("/api/live/automations/unknown/run", json=intent, headers=headers).status_code
        == 422
    )
    with client_for(replace(settings, enabled=False), store, provider, tmp_path) as disabled:
        assert disabled.post(url, json=intent, headers=headers).status_code == 409


def test_secret_remediation_handoff_checks_scope_and_atomically_queues_fresh_validator(
    setup, monkeypatch
):
    from app.automation.maintenance import finish_maintenance
    from app.automation.outbox import PublicationOutbox

    settings, store, provider, service = setup
    job = service.run_now(str(uuid4()), "secret_scan")
    store.update(
        job["id"],
        state="running",
        session_id="implementation",
        session_url="https://app.devin.ai/sessions/implementation",
    )
    job = store.get(job["id"])
    pr = {
        "state": "open",
        "head": {
            "sha": "b" * 40,
            "ref": f"cognition/automation/{job['id'][:12]}",
            "repo": {"full_name": settings.repo},
        },
        "base": {"ref": settings.branch, "repo": {"full_name": settings.repo}},
    }
    provider.pr = lambda number: pr
    report = {
        "task_complete": True,
        "pr_url": f"https://github.com/{settings.repo}/pull/8",
        "candidate_sha": "b" * 40,
        "summary": "Environment reference replaces hardcoded value",
        "tests": ["Synthetic configuration regression passed"],
        "blocker": "",
    }
    original = PublicationOutbox.prepare_github
    monkeypatch.setattr(
        PublicationOutbox, "prepare_github", lambda *args: {"key": "bad", "payload": object()}
    )
    with pytest.raises(TypeError):
        finish_maintenance(settings, store, provider, job, report)
    assert len(store.jobs()) == 1 and store.get(job["id"])["state"] == "running"
    assert store.publications() == []
    monkeypatch.setattr(PublicationOutbox, "prepare_github", original)
    finish_maintenance(settings, store, provider, job, report)
    finish_maintenance(settings, store, provider, job, report)
    child = next(j for j in store.jobs() if j["kind"] == "validation")
    assert child["payload"]["implementation_jobs"] == [job["id"]]
    assert child["payload"]["head_ref"] == pr["head"]["ref"]
    assert child["payload"]["automation_id"] == "secret_scan"
    from app.automation.prompts import execution_payload
    from app.automation.validation import ValidationService

    pr.update(draft=False, user={"login": settings.allowed_actor}, labels=[])
    assert ValidationService(settings, store, provider).is_current(child)
    prompt = execution_payload(settings, child, [])["prompt"]
    assert child["candidate_sha"] in prompt and "curl" in prompt
    assert len(store.jobs()) == 2 and len(store.publications()) == 1
    assert store.get(job["id"])["state"] == "prepared"
    pr["base"]["repo"]["full_name"] = "apache/superset"
    with pytest.raises(ValueError, match="target"):
        finish_maintenance(settings, store, provider, job, report)


def test_audit_and_maintenance_dispatch_use_correct_prompts_and_finish(setup):
    settings, store, provider, service = setup
    engine = Engine(replace(settings, max_sessions=10), store, provider)
    provider.requests = []

    def create(payload):
        provider.requests.append(payload)
        return {"session_id": "test-session", "url": "https://app.devin.ai/sessions/test-session"}

    provider.create_session = create
    review = service.run_now(str(uuid4()), "release_readiness")
    engine.tick()
    assert "Read-only review" in provider.requests[-1]["prompt"]
    provider.response = {
        "status": "running",
        "status_detail": "finished",
        "structured_output": {
            "task_complete": True,
            "summary": "No open release blockers",
            "observations": [],
            "blocker": "",
        },
    }
    engine.poll(store.get(review["id"]))
    assert store.get(review["id"])["state"] == "completed"
    scan = service.run_now(str(uuid4()), "secret_scan")
    engine.tick()
    assert "hardcoded" in provider.requests[-1]["prompt"]
    provider.response = {
        "status": "running",
        "status_detail": "finished",
        "structured_output": {
            "task_complete": True,
            "summary": "No confirmed secret found",
            "tests": ["Redacted scan complete"],
            "pr_url": "",
            "candidate_sha": "",
            "blocker": "",
        },
    }
    engine.poll(store.get(scan["id"]))
    assert store.get(scan["id"])["state"] == "completed"
    assert store.publications() == []


def test_maintenance_does_not_duplicate_open_pr_and_skips_unchanged_scheduled_revision(setup):
    _, store, provider, service = setup
    first = service.run_now(str(uuid4()), "secret_scan")
    store.update(first["id"], state="prepared", pr_number=11)
    provider.pr = lambda number: {"state": "open"}
    row = service.schedule("secret_scan")
    service.configure(True, 86400, row["updated"], "secret_scan")

    def due():
        with store.connect() as c:
            c.execute("UPDATE schedules SET next_run=1 WHERE id='secret_scan'")

    due()
    assert service.tick("secret_scan")["id"] == first["id"]
    with pytest.raises(ScheduleConflict):
        service.run_now(str(uuid4()), "secret_scan")
    provider.pr = lambda number: {"state": "closed"}
    due()
    assert service.tick("secret_scan")["id"] == first["id"]
    assert store.get(first["id"])["state"] == "completed"
    assert len(store.jobs()) == 1
    provider.gh = lambda *args, **kwargs: {"sha": "b" * 40}
    due()
    assert service.tick("secret_scan")["id"] != first["id"]
    assert len(store.jobs()) == 2


def test_maintenance_owns_pr_and_defers_patch_intake(setup):
    from app.automation.patches import PatchService

    settings, store, provider, service = setup
    first = service.run_now(str(uuid4()), "secret_scan")
    store.update(first["id"], state="running")
    patches = PatchService(settings, store, provider)
    with pytest.raises(ValueError, match="handoff pending"):
        patches.accept(11, "poll")
    store.update(first["id"], state="prepared", pr_number=11)
    assert patches.accept(11, "poll")["id"] == first["id"]
    duplicate = store.enqueue("duplicate", "patch", {}, pr_number=11)
    assert patches.preflight(duplicate) is False
    assert store.get(duplicate["id"])["state"] == "blocked"


def test_scan_cannot_treat_unavailable_sources_or_missing_output_as_clean(setup):
    settings, store, provider, service = setup
    engine = Engine(settings, store, provider)
    job = service.run_now(str(uuid4()), "dependency_vulnerabilities")
    with pytest.raises(ValueError):
        engine.finish_scan(job, {"task_complete": True, "summary": "No output"})
    assert store.get(job["id"])["state"] == "queued"
    engine.finish_scan(
        job,
        {
            "task_complete": True,
            "summary": "Could not scan",
            "findings": [],
            "blocker": "Advisory API unavailable",
        },
    )
    assert store.get(job["id"])["state"] == "needs_attention"
    assert len(store.jobs()) == 1


def test_one_recipe_failure_is_visible_but_does_not_stop_other_schedules(setup, monkeypatch):
    _, store, _, service = setup
    seen = []

    def tick(identity):
        seen.append(identity)
        if identity == "code_patterns":
            raise RuntimeError("unavailable")

    monkeypatch.setattr(service, "tick", tick)
    with pytest.raises(ScheduleConflict, match="code_patterns"):
        service.tick_all()
    assert seen == list(RECIPES)
    assert store.recall("schedule_error:code_patterns")["error"] == "RuntimeError"


def test_maintenance_missing_handoff_and_blocked_scan_cannot_pass(setup):
    from app.automation.maintenance import finish_maintenance

    settings, store, provider, service = setup
    job = service.run_now(str(uuid4()), "secret_scan")
    result = {
        "task_complete": True,
        "summary": "Scan unavailable",
        "tests": [],
        "pr_url": "",
        "candidate_sha": "",
        "blocker": "Scanner installation failed",
    }
    with pytest.raises(ValueError):
        finish_maintenance(
            settings, store, provider, job, {k: v for k, v in result.items() if k != "blocker"}
        )
    assert store.get(job["id"])["state"] == "queued"
    finish_maintenance(settings, store, provider, job, result)
    assert store.get(job["id"])["state"] == "needs_attention"
    assert store.publications() == []


def test_completed_maintenance_keeps_analytics_implementation_provenance(tmp_path):
    from unittest.mock import patch

    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(database=str(tmp_path / "live.db"))
    with TestClient(create_app(settings, demo_database=tmp_path / "demo.db")) as client:
        store = client.app.state.engine.store
        job = store.enqueue("maintenance", "maintenance", {}, pr_number=7, candidate_sha="a" * 40)
        store.update(job["id"], state="completed", session_id="confirmed-session")
        with patch("app.analytics.routes.analyze", return_value={}) as analyze:
            response = client.get(
                "/api/analytics/pull-requests", params={"repository": settings.repo}
            )
            assert response.status_code == 200
            assert analyze.call_args.kwargs["completed"] == {7}
