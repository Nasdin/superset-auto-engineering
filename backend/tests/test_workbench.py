"""Read-only queue explanations and evidence provenance, using local ledger fixtures."""

from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.store import Store
from app.automation.workbench import execution_context, pull_request_rows

SHA = "a" * 40
SESSION = "https://app.devin.ai/sessions/paused-fixture"
BLOCKER = "Minor gaps: final logout screenshot missing due to a session suspension."


@pytest.fixture
def ledger(tmp_path):
    return Store(tmp_path / "workbench.db")


def settings(**kwargs):
    return replace(
        Settings(enabled=True, devin_key="fixture", github_token="fixture", max_sessions=20),
        **kwargs,
    )


def context(db, config=None, **kwargs):
    return execution_context(
        config or settings(), db.operational_jobs(), {"at": 1000}, now=1001, **kwargs
    )


def enqueue(db, kind="validation", number=6, **payload):
    return db.enqueue(
        f"fixture:{kind}:{number}", kind, payload, candidate_sha=SHA, pr_number=number
    )


def test_paused_session_explains_other_pr_queue_without_claiming_credit_exhaustion(ledger):
    paused = enqueue(ledger, "dependency")
    ledger.update(
        paused["id"],
        state="needs_attention",
        session_id="paused-fixture",
        session_url=SESSION,
        error=BLOCKER,
    )
    enqueue(ledger, number=7)
    execution = context(ledger)
    rows = {r["number"]: r for r in pull_request_rows([], ledger.operational_jobs(), [], execution)}
    assert execution["sessions_used"] == 1 and execution["sessions_remaining"] == 19
    assert execution["blockers"] == [
        {
            "code": "session_hold",
            "job_id": paused["id"],
            "pr_number": 6,
            "state": "needs_attention",
            "session_url": SESSION,
            "message": BLOCKER,
        }
    ]
    assert rows[7]["progress"]["detail"] == BLOCKER
    assert rows[7]["progress"]["blocker"]["session_url"] == SESSION
    assert rows[6]["progress"]["session_url"] == SESSION
    assert not rows[6]["progress"]["ready"]


@pytest.mark.parametrize("state", ["blocked", "dead_letter"])
@pytest.mark.parametrize("session_id", ["fixture", ""])
def test_only_session_bearing_failed_jobs_globally_hold_dispatch(ledger, state, session_id):
    job = enqueue(ledger)
    ledger.update(job["id"], state=state)
    assert not context(ledger)["blockers"]
    ledger.update(job["id"], session_id=session_id, session_url=SESSION)
    assert context(ledger)["blockers"][0]["code"] == "session_hold"


def test_budget_explanation_counts_lifetime_sessions_and_reserved_followups(ledger):
    old = enqueue(ledger, number=4)
    ledger.update(old["id"], state="completed", session_id="finished")
    enqueue(ledger, "dependency", work_type="dependency")
    execution = context(ledger, settings(max_sessions=2))
    assert execution["sessions_used"] == ledger.session_count(excluding="none") == 1
    row = pull_request_rows([], ledger.operational_jobs(), [], execution)[0]
    assert row["progress"]["blocker"]["code"] == "session_budget"
    assert "reserves 2 session slot(s)" in row["progress"]["detail"]
    assert "not the organization's credit balance" in row["progress"]["detail"]


def test_disabled_dependencies_and_worker_provider_holds_are_visible(ledger):
    enqueue(ledger, "dependency", work_type="dependency")
    execution = execution_context(
        settings(enabled=False, dependabot_enabled=False, devin_key=""),
        ledger.operational_jobs(),
        {},
        [{"provider": "devin", "state": "open", "reason": "credits", "retry_at": 0}],
        now=1000,
    )
    assert {b["code"] for b in execution["blockers"]} == {
        "disabled",
        "configuration",
        "provider_hold",
        "worker_stale",
    }
    row = pull_request_rows([], ledger.operational_jobs(), [], execution)[0]
    assert row["progress"]["blocker"]["code"] == "dependency_disabled"


def test_running_session_is_distinct_from_attention_hold(ledger):
    run = enqueue(ledger, number=4)
    ledger.update(run["id"], state="running", session_id="working", session_url=SESSION)
    enqueue(ledger, number=6)
    rows = pull_request_rows([], ledger.operational_jobs(), [], context(ledger))
    assert rows[0]["progress"]["label"] == "Queued · another run is active"
    assert rows[1]["progress"]["label"] == "Devin validating"


def ready_result():
    return {
        "candidate_sha": SHA,
        "ci": {"state": "success", "sha": SHA},
        "gate": "review_ready",
        "gate_failures": [],
        "provenance": "independent_devin_session",
    }


def test_ready_signal_is_recorded_sha_scoped_and_new_run_supersedes_it(ledger):
    job = enqueue(ledger)
    ledger.update(job["id"], state="review_ready", result=ready_result())
    row = pull_request_rows([], ledger.operational_jobs(), [])[0]
    assert row["progress"]["ready"] and row["progress"]["candidate_sha"] == SHA
    assert "Confirm the current head" in row["progress"]["detail"]
    ledger.enqueue("new-candidate", "validation", {}, candidate_sha="b" * 40, pr_number=6)
    row = pull_request_rows([], ledger.operational_jobs(), [])[0]
    assert not row["progress"]["ready"]
    assert row["progress"]["state"] == "queued"


@pytest.mark.parametrize(
    "invalid",
    [
        {"ci": {"state": "pending", "sha": SHA}},
        {"ci": {"state": "success", "sha": "b" * 40}},
        {"candidate_sha": "b" * 40},
        {"provenance": "unverified_validation"},
        {"gate_failures": ["Missing artifact"]},
        {"gate": "validation_failed"},
    ],
)
def test_legacy_or_inconsistent_ready_state_does_not_get_green_signal(ledger, invalid):
    job = enqueue(ledger)
    ledger.update(job["id"], state="review_ready", result={**ready_result(), **invalid})
    progress = pull_request_rows([], ledger.operational_jobs(), [])[0]["progress"]
    assert not progress["ready"] and progress["label"] == "Readiness needs verification"


def test_revision_receipts_bind_to_job_and_destination_including_integration_members(ledger):
    job = enqueue(ledger, number=10, members=[{"pr_number": 6}])
    ledger.update(job["id"], state="review_ready", result=ready_result())
    jid = job["id"]
    keys = [
        f"github:{jid}:10:revision",
        f"github:{jid}:6:revision",
        f"github:validation-status-v2:{jid}:10",
        f"slack:{jid}:revision",
        f"github-ready:{jid}:{SHA}:revision",
        f"github:{jid}:99:revision",
        "github:unrelated:10:revision",
    ]
    rows = {
        r["number"]: r
        for r in pull_request_rows(
            [], ledger.operational_jobs(), [{"key": key, "state": "sent"} for key in keys]
        )
    }
    assert [p["key"] for p in rows[10]["publications"]] == [keys[0], *keys[2:5]]
    assert [p["key"] for p in rows[6]["publications"]] == [keys[1], keys[3]]
    assert rows[10]["publications"][-1]["purpose"] == "readiness"
    assert rows[6]["progress"]["label"] == "Integrated evidence ready"
    assert "integration PR #10" in rows[6]["progress"]["detail"]


def test_workbench_api_exposes_cached_blocker_without_provider_calls(ledger, tmp_path):
    from app.analytics.store import AnalyticsStore
    from app.automation import routes
    from app.automation.engine import Engine
    from app.main import create_app
    from fastapi.testclient import TestClient

    class NoProviders:
        store = None

        def __getattr__(self, name):
            raise AssertionError(f"Read model must not contact provider: {name}")

    config = settings(database=str(tmp_path / "api.db"))
    engine = Engine(config, ledger, NoProviders())
    app = create_app(config, demo_database=tmp_path / "demo.db")
    app.dependency_overrides[routes.get_engine] = lambda: engine
    app.state.analytics = AnalyticsStore(tmp_path / "analytics.db")
    job = enqueue(ledger, "dependency", work_type="dependency")
    ledger.update(
        job["id"], state="needs_attention", session_id="fixture", session_url=SESSION, error=BLOCKER
    )
    response = TestClient(app).get("/api/live/pull-requests?bot_only=true")
    assert response.status_code == 200
    data = response.json()
    assert data["execution"]["blockers"][0]["message"] == BLOCKER
    assert data["execution"]["sessions_remaining"] == 19
    assert data["rows"][0]["progress"]["session_url"] == SESSION


@pytest.mark.parametrize(
    "state,session_id,kind,count",
    [
        ("completed", "", "validation", 1),
        ("unknown_effect", None, "repair", 1),
        ("dispatching", None, "repair", 1),
        ("completed", "fixture", "integration", 0),
        ("queued", None, "validation", 0),
    ],
)
def test_displayed_session_usage_matches_store_exactly(ledger, state, session_id, kind, count):
    job = enqueue(ledger, kind)
    ledger.update(job["id"], state=state, session_id=session_id)
    assert context(ledger)["sessions_used"] == ledger.session_count(excluding="none") == count
