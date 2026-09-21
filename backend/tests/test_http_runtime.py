"""Fault injection at the real ASGI boundary; no external providers are called."""

import asyncio
import threading
from dataclasses import replace

import httpx
import pytest
from app.auth import AuthSettings
from app.automation.config import Settings
from app.database import Database, DatabaseLimits
from app.main import create_app
from app.passwords import hash_password
from fastapi.testclient import TestClient
from sqlalchemy.exc import InternalError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeout


def make_app(tmp_path, **kwargs):
    return create_app(
        replace(Settings(), database=str(tmp_path / "live.db")),
        demo_database=tmp_path / "demo.db",
        **kwargs,
    )


@pytest.mark.parametrize(
    "failure", [OperationalError("secret SQL", {}, Exception("secret")), PoolTimeout("secret")]
)
def test_database_outage_fails_closed_with_safe_correlated_503(
    tmp_path, monkeypatch, caplog, failure
):
    app = make_app(tmp_path, auth_settings=AuthSettings(True, hash_password("test")))

    def unavailable(*_):
        raise failure

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.reviewer_auth, "authenticated", unavailable)
        response = client.get("/api/live/overview")
        assert response.status_code == 503
        assert response.json()["code"] == "database_unavailable"
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert response.headers["retry-after"] == "5"
        assert response.headers["cache-control"] == "no-store"
        assert "secret" not in response.text and "secret" not in caplog.text
        # Liveness remains available without bypassing authentication for protected data.
        assert client.get("/api/health/live").status_code == 200


@pytest.mark.parametrize("stage", ["auth", "route"])
def test_slow_sync_route_and_auth_do_not_block_event_loop(tmp_path, monkeypatch, stage):
    app = make_app(tmp_path, auth_settings=AuthSettings(True, hash_password("test")))
    entered, release = threading.Event(), threading.Event()

    def slow_io(*_):
        entered.set()
        assert release.wait(3), "Test cleanup must release the blocking operation"
        return True if stage == "auth" else []

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = asyncio.create_task(client.get("/api/live/overview"))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                live = await asyncio.wait_for(client.get("/api/health/live"), 1)
                assert live.status_code == 200 and not pending.done()
            finally:
                release.set()
            assert (await pending).status_code == 200

    with TestClient(app):
        monkeypatch.setattr(app.state.reviewer_auth, "authenticated", lambda *_: True)
        if stage == "auth":
            monkeypatch.setattr(app.state.reviewer_auth, "authenticated", slow_io)
        else:
            monkeypatch.setattr(app.state.engine.store, "operational_jobs", slow_io)
        asyncio.run(scenario())


def test_readiness_reports_unavailable_without_poisoning_next_request(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        store = app.state.engine.store
        original = store.connect

        def unavailable():
            raise PoolTimeout("private")

        monkeypatch.setattr(store, "connect", unavailable)
        assert client.get("/api/health").status_code == 503
        assert client.get("/api/health/live").status_code == 200
        monkeypatch.setattr(store, "connect", original)
        assert client.get("/api/health").status_code == 200


def test_startup_failure_closes_previously_acquired_resources(tmp_path, monkeypatch):
    import app.main as main

    closed = []
    original_close = Database.close

    def close(database):
        closed.append(database)
        original_close(database)

    def fail(*_):
        raise RuntimeError("Superset startup failed")

    monkeypatch.setattr(Database, "close", close)
    monkeypatch.setattr(main, "SupersetClient", fail)
    monkeypatch.setenv("SUPERSET_INTERNAL_URL", "http://test")
    monkeypatch.setenv("ANALYTICS_SUPERSET_SERVICE_PASSWORD", "test-only")
    app = make_app(tmp_path)
    with pytest.raises(RuntimeError, match="Superset startup failed"), TestClient(app):
        pytest.fail("Startup must fail")
    assert len(closed) == 2 and closed[0] is not closed[1]


@pytest.mark.parametrize(
    "name",
    ["pool_size", "pool_timeout", "connect_timeout", "statement_timeout_ms", "lock_timeout_ms"],
)
def test_database_cannot_be_configured_with_unlimited_waits(name):
    with pytest.raises(ValueError):
        DatabaseLimits(**{name: 0})
    with pytest.raises(ValueError):
        DatabaseLimits(max_overflow=-1)


def test_database_limits_resolve_at_runtime(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    assert DatabaseLimits.from_env().pool_size == 4
    assert DatabaseLimits.from_env().max_overflow == 0


def test_idle_transaction_disconnect_is_503_but_programming_errors_are_not(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    disconnected = Exception("private")
    disconnected.sqlstate = "25P03"
    failure = InternalError("private SQL", {}, disconnected)

    def unavailable():
        raise failure

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.engine.store, "connect", unavailable)
        assert client.get("/api/health").status_code == 503
        failure = ProgrammingError("bad SQL", {}, Exception("syntax error"))
        with pytest.raises(ProgrammingError):
            client.get("/api/health")


def test_analytics_overload_rejects_before_allocating_history_and_releases_slot(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    app = make_app(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_history(repository):
        calls.append(repository)
        entered.set()
        assert release.wait(3)
        raise RuntimeError("injected analysis failure")

    with TestClient(app) as client:
        original = app.state.analytics.pulls
        monkeypatch.setattr(app.state.analytics, "pulls", blocked_history)
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(client.get, "/api/analytics/pull-requests")
            try:
                assert entered.wait(2)
                rejected = client.get("/api/analytics/pull-requests")
                assert rejected.status_code == 503
                assert rejected.headers["retry-after"] == "2"
                assert calls == ["apache/superset"]
                assert client.get("/api/health/live").status_code == 200
            finally:
                release.set()
            with pytest.raises(RuntimeError, match="injected analysis failure"):
                first.result()
        monkeypatch.setattr(app.state.analytics, "pulls", original)
        assert client.get("/api/analytics/pull-requests").status_code == 200
