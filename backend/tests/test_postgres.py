"""Real Postgres tests. The URL must identify a dedicated disposable *_test database."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.analytics.embedding import Selection, remember_selection
from app.analytics.embedding import router as embedding_router
from app.analytics.metrics import analyze
from app.analytics.store import AnalyticsStore
from app.automation.store import Store
from app.database import Database, DatabaseLimits
from app.schema import analytics, automation
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url


@pytest.fixture
def postgres():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing a non-test Postgres database")
    database = Database(url)
    with database.engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS reporting CASCADE"))
        analytics.drop_all(c)
        automation.drop_all(c)
    store = Store(url)
    history = AnalyticsStore(url)
    yield store, history
    store.database.close()
    history.database.close()
    database.close()


def test_postgres_claim_is_single_flight_across_connections(postgres):
    store, _ = postgres
    for n in range(8):
        store.enqueue(str(n), "repair", {})
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: store.claim(), range(8)))
    assert len([job for job in claims if job]) == 1
    assert len([job for job in store.jobs() if job["state"] == "dispatching"]) == 1


def test_postgres_delivered_receipt_survives_restart_without_repost(postgres):
    store, _ = postgres
    store.queue_publication("one", {"provider": "github", "number": 4})
    assert store.claim_publication()["key"] == "one"
    store.finish_publication("one", "delivered", receipt={"id": 123})
    restarted = Store(store.path)
    try:
        assert restarted.claim_publication()["receipt"] == {"id": 123}
        assert store.claim_publication() is None
    finally:
        restarted.database.close()


def test_postgres_supersession_rolls_back_on_failure(postgres):
    store, _ = postgres
    job = store.enqueue("one", "validation", {}, candidate_sha="a" * 40, pr_number=4)
    with store.connect() as c:
        c.execute("ALTER TABLE jobs ADD CONSTRAINT no_stale CHECK (state <> 'stale')")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        store.supersede_validation(job, "b" * 40, "Nasdin/superset")
    assert len(store.jobs()) == 1 and store.get(job["id"])["state"] == "queued"


def test_postgres_epoch_precision_and_audit_sequence(postgres):
    store, _ = postgres
    before = time.time()
    job = store.enqueue("one", "repair", {})
    assert abs(job["created"] - before) < 1
    store.audit(job["id"], "created", {})
    store.audit(job["id"], "readback", {})
    assert store.has_audit(job["id"], "readback")


def test_migration_preserves_sources_and_refuses_existing_data(postgres, tmp_path):
    import importlib.util

    path = Path(__file__).parents[2] / "scripts/migrate_postgres.py"
    spec = importlib.util.spec_from_file_location("migrate_postgres", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ledger = tmp_path / "legacy.db"
    history_path = tmp_path / "history.db"
    legacy = Store(ledger)
    history = AnalyticsStore(history_path)
    job = legacy.enqueue("legacy", "repair", {"title": "Preserve me"})
    legacy.audit(job["id"], "created", {"source": "migration test"})
    legacy.queue_publication("legacy-comment", {"number": 4})
    legacy.finish_publication("legacy-comment", "delivered", receipt={"id": 99})
    legacy.database.close()
    history.database.close()
    before = (ledger.read_bytes(), history_path.read_bytes())
    store, _ = postgres
    counts = module.migrate(store.path, ledger, history_path)
    assert counts["jobs"] == 1 and counts["publications"] == 1
    assert store.get(job["id"])["payload"]["title"] == "Preserve me"
    assert store.claim_publication()["receipt"] == {"id": 99}
    store.audit(job["id"], "after migration", {})
    assert store.has_audit(job["id"], "after migration")
    with pytest.raises(ValueError, match="not empty"):
        module.migrate(store.path, ledger, history_path)
    assert before == (ledger.read_bytes(), history_path.read_bytes())


def test_embedding_endpoint_limits_resources_filters_and_provider_errors(postgres, monkeypatch):
    store, history = postgres
    app = FastAPI()
    app.include_router(embedding_router)
    app.state.engine = SimpleNamespace(
        store=store, settings=SimpleNamespace(database=store.path, repo="Nasdin/superset")
    )
    app.state.analytics = history
    calls = []

    def token(dashboard, selection):
        calls.append((dashboard, selection))
        return "short-lived-guest"

    app.state.superset = SimpleNamespace(guest_token=token)
    monkeypatch.setenv("SUPERSET_PUBLIC_URL", "https://example.com/bi")
    with TestClient(app) as client:
        assert client.post("/api/analytics/superset/session").status_code == 503
        store.remember("superset_dashboard", {"dashboard_id": "fixed-dashboard"})
        response = client.post(
            "/api/analytics/superset/session?repository=apache/superset&dashboard_id=attacker"
        )
        assert response.headers["Cache-Control"] == "no-store"
        result = response.json()
        assert (
            result["dashboard_id"] == "fixed-dashboard" and result["token"] == "short-lived-guest"
        )
        assert calls == [("fixed-dashboard", result["selection_id"])]
        with history.connect() as c:
            assert (
                c.execute(
                    "SELECT repository FROM analytics_selections WHERE selection_id=:id",
                    {"id": result["selection_id"]},
                ).fetchone()["repository"]
                == "apache/superset"
            )
        for query in (
            "repository=unapproved/repo",
            "days=1000",
            "end=2035-01-01",
            "comparison=custom",
        ):
            assert client.post("/api/analytics/superset/session?" + query).status_code == 422
        assert len(calls) == 1

        def unavailable(*_):
            raise httpx.ConnectError("private infrastructure details")

        app.state.superset = SimpleNamespace(guest_token=unavailable)
        response = client.post("/api/analytics/superset/session")
        assert response.status_code == 502 and "private infrastructure" not in response.text


def test_postgres_sql_views_match_reference_windows_filters_and_small_samples(postgres):
    store, history = postgres
    now = datetime.now(UTC)
    end = now.date() - timedelta(days=1)
    selection = Selection(end=end, days=30)
    values = selection.resolved("Nasdin/superset")
    baseline = date.fromisoformat(values["baseline_end"])
    pulls = []
    for i in range(14):
        merged = datetime.combine(end if i < 7 else baseline, datetime.min.time(), UTC)
        created = merged - timedelta(hours=24 if i < 7 else 48)
        pulls.append(
            {
                "number": i + 1,
                "title": "fix: sample" if i % 2 else "feat: sample",
                "html_url": f"https://github.com/apache/superset/pull/{i + 1}",
                "user": {"login": "engineer"},
                "labels": [{"name": "bug"}] if i % 2 else [],
                "base": {"ref": "master"},
                "state": "closed",
                "created_at": created.isoformat(),
                "merged_at": merged.isoformat(),
                "closed_at": merged.isoformat(),
                "updated_at": now.isoformat(),
            }
        )
    history.upsert("apache/superset", pulls)
    history.set_status(
        "apache/superset",
        {
            "state": "ready",
            "complete": True,
            "coverage_from": "2020-01-01",
            "last_success": now.isoformat(),
        },
    )
    # Test role is created explicitly by CI/local test setup.
    with store.connect() as c:
        for statement in (
            (Path(__file__).parents[1] / "app/analytics/reporting.sql").read_text().split(";")
        ):
            if statement.strip():
                c.execute(statement)
    for kind in ("", "fix", "feature", "dependency"):
        params = {**values, "kind": kind}
        identity = remember_selection(history, params)
        expected = analyze(
            history.pulls("apache/superset"),
            history.status("apache/superset"),
            end=end,
            days=30,
            baseline_end=baseline,
            kind=kind,
        )
        with history.connect() as c:
            actual = c.execute(
                "SELECT * FROM reporting.comparison WHERE selection_id=:id", {"id": identity}
            ).fetchone()
            trend = c.execute(
                "SELECT * FROM reporting.trend WHERE selection_id=:id ORDER BY window_end",
                {"id": identity},
            ).fetchall()
        assert actual["current_median_hours"] == expected["current"]["median_hours"]
        assert actual["baseline_median_hours"] == expected["baseline"]["median_hours"]
        assert actual["median_change_percent"] == expected["change_percent"]
        assert [r["median_hours"] for r in trend] == [r["median_hours"] for r in expected["trend"]]
    # User-controlled strings are bound values; they cannot broaden the selected rows.
    identity = remember_selection(history, {**values, "author": "engineer' OR true --"})
    with history.connect() as c:
        assert (
            c.execute(
                "SELECT merged_prs FROM reporting.comparison WHERE selection_id=:id",
                {"id": identity},
            ).fetchone()["merged_prs"]
            == 0
        )


def test_postgres_schedule_and_manual_intents_are_single_flight(postgres):
    from dataclasses import replace
    from uuid import uuid4

    from app.automation.config import Settings
    from app.automation.schedules import ScheduleService
    from test_automation import FakeProvider

    store, _ = postgres
    provider = FakeProvider()
    provider.gh = lambda *args, **kwargs: {"sha": "a" * 40}
    service = ScheduleService(replace(Settings(), database=store.path), store, provider)
    request_id = str(uuid4())
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: service.run_now(request_id), range(4)))
    assert len({j["id"] for j in jobs}) == 1
    store.update(jobs[0]["id"], state="completed")
    service.schedule()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: service.tick(), range(4)))
    assert len(store.jobs()) == 2


def test_postgres_recovery_intent_is_atomic_under_concurrency(postgres):
    from uuid import uuid4

    from app.automation.recovery_routes import replay

    store, _ = postgres
    job = store.enqueue("retry-concurrent", "repair", {})
    store.update(job["id"], state="dead_letter")
    engine = SimpleNamespace(store=store)
    intent = uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: replay(engine, "job", job["id"], intent), range(8)))
    assert all(r == responses[0] for r in responses)
    with store.connect() as c:
        assert (
            c.execute("SELECT COUNT(*) AS n FROM audit WHERE kind='operator_recovery'").fetchone()[
                "n"
            ]
            == 1
        )
    assert store.get(job["id"])["state"] == "queued"


def test_postgres_gate_outbox_transaction_and_restart(postgres):
    store, _ = postgres
    job = store.enqueue("gate-transaction", "validation", {})
    store.update(job["id"], state="running", session_id="existing")
    reports = [
        {"key": "first", "payload": {"body": "evidence"}},
        {"key": "invalid", "payload": {object()}},
    ]
    with pytest.raises(TypeError):
        store.commit_validation(job["id"], "review_ready", {}, None, reports)
    assert not store.publications() and store.get(job["id"])["state"] == "running"
    store.commit_validation(job["id"], "review_ready", {}, None, reports[:1])
    restarted = Store(store.path)
    try:
        assert restarted.get(job["id"])["state"] == "review_ready"
        assert restarted.claim_publication()["key"] == "first"
    finally:
        restarted.database.close()


def test_postgres_webhook_inbox_survives_restart(postgres):
    from app.automation.inbox import Inbox

    store, _ = postgres
    inbox = Inbox(SimpleNamespace(store=store))
    assert inbox.accept("delivery", {"event": "issues", "number": 1})["status"] == "queued"
    restarted = Store(store.path)
    try:
        later = Inbox(SimpleNamespace(store=restarted))
        assert later.accept("delivery", {"event": "issues", "number": 1})["status"] == "duplicate"
        assert later.claim()["payload"]["number"] == 1
        assert inbox.claim() is None
    finally:
        restarted.database.close()


def test_postgres_limits_cancel_slow_query_then_recover(postgres):
    from sqlalchemy.exc import OperationalError

    store, _ = postgres
    db = Database(store.path, limits=DatabaseLimits(statement_timeout_ms=50))
    try:
        with pytest.raises(OperationalError, match="statement timeout"), db.connect() as c:
            c.execute("SELECT pg_sleep(1)")
        with db.connect() as c:
            assert c.execute("SELECT 1 AS alive").fetchone()["alive"] == 1
            assert c.execute("SHOW lock_timeout").fetchone()["lock_timeout"] == "5s"
    finally:
        db.close()


def test_postgres_pool_saturation_is_bounded_and_recovers(postgres):
    from sqlalchemy.exc import TimeoutError

    store, _ = postgres
    db = Database(store.path, limits=DatabaseLimits(pool_size=1, max_overflow=0, pool_timeout=1))
    try:
        with db.connect() as first:
            first.execute("SELECT 1")
            with pytest.raises(TimeoutError), db.connect():
                pytest.fail("A saturated pool must not grow past its budget")
        with db.connect() as c:
            assert c.execute("SELECT 1 AS alive").fetchone()["alive"] == 1
    finally:
        db.close()


@pytest.mark.parametrize("cadence", ["monthly", "rolling"])
def test_superset_mobile_layout_uses_fixed_dashboard_with_same_row_scope(
    postgres, monkeypatch, cadence
):
    store, history = postgres
    app = FastAPI()
    app.include_router(embedding_router)
    app.state.engine = SimpleNamespace(
        store=store, settings=SimpleNamespace(database=store.path, repo="Nasdin/superset")
    )
    app.state.analytics = history
    calls = []

    def token(dashboard, selection):
        calls.append((dashboard, selection))
        return "guest"

    app.state.superset = SimpleNamespace(guest_token=token)
    monkeypatch.setenv("SUPERSET_PUBLIC_URL", "https://example.com/bi")
    store.remember(
        "superset_dashboard", {"dashboard_id": "monthly", "rolling_dashboard_id": "rolling"}
    )
    with TestClient(app) as client:
        assert client.post("/api/analytics/superset/session?layout=mobile").status_code == 503
        store.remember(
            "superset_dashboard",
            {
                "dashboard_id": "monthly",
                "rolling_dashboard_id": "rolling",
                "mobile_dashboard_id": "mobile-monthly",
                "mobile_rolling_dashboard_id": "mobile-rolling",
            },
        )
        desktop = client.post(f"/api/analytics/superset/session?cadence={cadence}").json()
        mobile = client.post(
            f"/api/analytics/superset/session?cadence={cadence}&layout=mobile&dashboard_id=attacker"
        ).json()
        assert desktop["selection_id"] == mobile["selection_id"]
        assert calls == [
            (cadence, desktop["selection_id"]),
            ("mobile-" + cadence, desktop["selection_id"]),
        ]
        assert client.post("/api/analytics/superset/session?layout=attacker").status_code == 422


@pytest.fixture(params=["sqlite", "postgres"])
def handoff_store(request, tmp_path):
    if request.param == "postgres":
        return request.getfixturevalue("postgres")[0]
    store = Store(tmp_path / "handoff.db")
    request.addfinalizer(store.database.close)
    return store


def test_handoff_rolls_back_state_child_and_all_reports(handoff_store):
    store = handoff_store
    job = store.enqueue("parent", "dependency", {})
    store.update(job["id"], state="running")
    with pytest.raises(TypeError):
        store.commit_handoff(
            job["id"],
            values={"state": "prepared", "result": {"candidate_sha": "a" * 40}},
            followups=[
                {"key": "child", "kind": "validation", "payload": {}, "parent_id": job["id"]}
            ],
            publications=[
                {"key": "valid", "payload": {"body": "ready"}},
                {"key": "invalid", "payload": {"body": object()}},
            ],
        )
    assert store.get(job["id"])["state"] == "running"
    assert store.get(job["id"])["result"] is None
    assert store.by_key("child") is None
    assert store.publications() == []


def test_handoff_restart_and_replay_preserve_child_and_receipt(handoff_store):
    store = handoff_store
    job = store.enqueue("parent", "dependency", {})
    handoff = {
        "values": {"state": "prepared", "candidate_sha": "a" * 40},
        "followups": [
            {"key": "child", "kind": "validation", "payload": {}, "parent_id": job["id"]}
        ],
        "publications": [{"key": "report", "payload": {"provider": "github", "number": 7}}],
    }
    assert store.commit_handoff(job["id"], **handoff)
    store.database.close()
    restarted = Store(store.path)
    try:
        assert restarted.get(job["id"])["state"] == "prepared"
        assert restarted.by_key("child")["parent_id"] == job["id"]
        assert restarted.claim_publication()["key"] == "report"
        restarted.finish_publication("report", "delivered", receipt={"id": 123})
        assert restarted.commit_handoff(job["id"], **handoff)
        assert len(restarted.jobs()) == 2
        assert len(restarted.publications()) == 1
        assert restarted.claim_publication()["receipt"] == {"id": 123}
    finally:
        restarted.database.close()


@pytest.mark.parametrize("missing", [False, True])
def test_handoff_rejects_stale_or_missing_parent(handoff_store, missing):
    store = handoff_store
    job = store.enqueue("parent", "dependency", {})
    store.update(job["id"], state="stale")
    assert not store.commit_handoff(
        "missing" if missing else job["id"],
        values={"state": "prepared"},
        followups=[{"key": "child", "kind": "validation", "payload": {}}],
        publications=[{"key": "report", "payload": {}}],
    )
    assert store.get(job["id"])["state"] == "stale"
    assert store.by_key("child") is None
    assert store.publications() == []


def test_postgres_disconnect_mid_handoff_rolls_back_and_allows_retry(postgres, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    store, _ = postgres
    job = store.enqueue("parent", "dependency", {})
    store.update(job["id"], state="running")
    handoff = {
        "values": {"state": "prepared"},
        "followups": [{"key": "child", "kind": "validation", "payload": {}}],
        "publications": [{"key": "report", "payload": {"body": "prepared"}}],
    }
    queue = store._queue_publication

    def disconnect_after_insert(connection, key, payload):
        queue(connection, key, payload)
        pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        # A second connection kills only this test's still-uncommitted transaction.
        with store.connect() as control:
            assert control.execute(
                "SELECT pg_terminate_backend(:pid) AS terminated", {"pid": pid}
            ).fetchone()["terminated"]
        connection.execute("SELECT 1")

    monkeypatch.setattr(store, "_queue_publication", disconnect_after_insert)
    with pytest.raises(DBAPIError):
        store.commit_handoff(job["id"], **handoff)
    assert store.get(job["id"])["state"] == "running"
    assert store.by_key("child") is None
    assert store.publications() == []
    monkeypatch.setattr(store, "_queue_publication", queue)
    assert store.commit_handoff(job["id"], **handoff)
    assert store.get(job["id"])["state"] == "prepared"
    assert store.by_key("child") is not None
    assert store.claim_publication()["key"] == "report"


def test_postgres_automation_schedules_and_provenance_survive_restart(postgres):
    from dataclasses import replace
    from uuid import uuid4

    from app.automation.config import Settings
    from app.automation.schedules import ScheduleService

    store, _ = postgres
    settings = replace(Settings(), database=store.path, scan_interval=0)
    provider = SimpleNamespace(gh=lambda *args, **kwargs: {"sha": "a" * 40})
    service = ScheduleService(settings, store, provider)
    row = service.schedule("code_patterns")
    enabled = service.configure(True, 3600, row["updated"], "code_patterns")
    intent = str(uuid4())
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: service.run_now(intent, "code_patterns"), range(4)))
    assert len({job["id"] for job in jobs}) == 1
    restarted = Store(store.path)
    try:
        after = ScheduleService(settings, restarted, provider)
        assert after.schedule("code_patterns")["updated"] == enabled["updated"]
        assert after.run_now(intent, "code_patterns")["id"] == jobs[0]["id"]
        history = after.overview()["automation_history"]
        assert history[0]["automations"][0]["id"] == "code_patterns"
    finally:
        restarted.database.close()


def test_feedback_compare_and_swap_is_atomic_across_postgres_connections(postgres):
    import uuid

    from app.automation.config import Settings
    from app.automation.feedback import FeedbackConflict, FeedbackService
    from app.automation.routes import FeedbackRequest

    store, _ = postgres
    job = store.enqueue("feedback-source", "scan", {})
    service = FeedbackService(Settings(), store)
    initial = FeedbackRequest(
        request_id=str(uuid.uuid4()),
        source_job_id=job["id"],
        author="Nasrudin",
        title="Preserve failures",
        reason="Agent summary contradicted tests",
        correction="Fail when counts report failures",
    ).model_dump(mode="json")
    receipt = service.save(initial)

    def edit(number):
        try:
            return service.save(
                {
                    **initial,
                    "request_id": str(uuid.uuid4()),
                    "feedback_id": receipt["feedback_id"],
                    "expected_revision": receipt["id"],
                    "correction": f"Revision {number}",
                }
            )
        except FeedbackConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, [1, 2]))
    assert results.count("conflict") == 1
    with store.connect() as c:
        assert (
            len(
                c.execute(
                    "SELECT * FROM lessons WHERE job_id=:id",
                    {"id": "feedback:" + receipt["feedback_id"]},
                ).fetchall()
            )
            == 2
        )
