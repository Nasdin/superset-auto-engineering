import hashlib
from dataclasses import replace

import pytest
from app.auth import COOKIE, AuthSettings, ReviewerAuth
from app.automation.config import Settings
from app.main import create_app
from app.passwords import hash_password
from fastapi.testclient import TestClient

PASSWORD = "integration-test-password"
INTENT = {"X-Cognition-Intent": "session"}


@pytest.fixture
def app(tmp_path):
    settings = replace(
        Settings(),
        database=str(tmp_path / "live.db"),
        operator_token="operator-test",
        webhook_secret="test-secret",
    )
    return create_app(
        settings,
        demo_database=tmp_path / "demo.db",
        auth_settings=AuthSettings(True, hash_password(PASSWORD), True),
    )


def signin(client):
    return client.post("/api/auth/login", json={"password": PASSWORD}, headers=INTENT)


def test_login_logout_and_operator_boundaries(app):
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/auth/session").json() == {"enabled": True, "authenticated": False}
        assert client.get("/api/live/overview").status_code == 401
        assert client.get("/openapi.json").status_code == 401
        assert client.post("/api/live/webhooks/github", json={}).status_code == 401
        assert client.get("/api/auth/verify").status_code == 401
        assert (
            client.post("/api/auth/login", json={"password": "wrong"}, headers=INTENT).status_code
            == 401
        )
        response = signin(client)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        token = client.cookies.get(COOKIE)
        with app.state.engine.store.connect() as connection:
            row = connection.execute("SELECT * FROM reviewer_sessions").fetchone()
            assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert client.get("/api/auth/session").json()["authenticated"]
        assert client.get("/api/auth/verify").status_code == 204
        assert client.get("/api/live/overview").status_code == 200
        assert client.post("/api/analytics/superset/session").status_code == 403
        assert (
            client.post(
                "/api/analytics/superset/session",
                headers={**INTENT, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        # Reviewer session does not satisfy operator authentication.
        assert client.post("/api/live/scan", headers=INTENT).status_code == 401
        assert client.post("/api/auth/logout", headers=INTENT).status_code == 200
        client.cookies.set(COOKIE, token)
        assert client.get("/api/live/overview").status_code == 401
        # Existing operator clients do not need a browser session.
        assert (
            client.get(
                "/api/live/overview", headers={"Authorization": "Bearer operator-test"}
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/live/overview", headers={"Authorization": "Bearer incorrect"}
            ).status_code
            == 401
        )


def test_expiry_password_rotation_and_forged_cookie(app):
    with TestClient(app, base_url="https://testserver") as client:
        signin(client)
        auth = app.state.reviewer_auth
        token = client.cookies.get(COOKIE)
        assert auth.authenticated(token)
        with auth.database.connect() as connection:
            connection.execute("UPDATE reviewer_sessions SET expires=0")
        assert client.get("/api/auth/session").json()["authenticated"] is False
        signin(client)
        token = client.cookies.get(COOKIE)
        replacement = ReviewerAuth(
            auth.database, AuthSettings(True, hash_password("different-password"), True)
        )
        assert not replacement.authenticated(token)
        assert not auth.authenticated("forged")
        assert not auth.authenticated("x" * 129)


def test_csrf_and_durable_rate_limit(app):
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 403
        assert (
            client.post(
                "/api/auth/login",
                json={"password": PASSWORD},
                headers={**INTENT, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        assert client.post("/api/auth/logout").status_code == 403
        for _ in range(20):
            assert (
                client.post(
                    "/api/auth/login", json={"password": "wrong"}, headers=INTENT
                ).status_code
                == 401
            )
        assert signin(client).status_code == 429
        # Limit is shared with a new auth instance, rather than just process memory.
        auth = app.state.reviewer_auth
        with pytest.raises(Exception) as error:
            ReviewerAuth(auth.database, auth.settings).login(PASSWORD)
        assert error.value.status_code == 429
        with auth.database.connect() as connection:
            connection.execute("UPDATE reviewer_login_limits SET started=0")
        assert signin(client).status_code == 200


def test_disabled_forward_auth_fails_closed_and_bad_configuration(monkeypatch, tmp_path):
    app = create_app(
        replace(Settings(), database=str(tmp_path / "live.db")),
        demo_database=tmp_path / "demo.db",
        auth_settings=AuthSettings(),
    )
    with TestClient(app) as client:
        assert client.get("/api/auth/session").json() == {"enabled": False, "authenticated": True}
        assert client.get("/api/auth/verify").status_code == 401
        assert (
            client.post("/api/auth/login", json={"password": PASSWORD}, headers=INTENT).status_code
            == 409
        )
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_PASSWORD_HASH", "")
    with pytest.raises(ValueError, match="configure_login"):
        AuthSettings.from_env()


def test_parallel_logins_bound_password_hash_memory(app, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    import app.auth as auth_module

    original = hashlib.scrypt
    lock = Lock()
    active = peak = 0

    def observe(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    with TestClient(app):
        monkeypatch.setattr(auth_module.hashlib, "scrypt", observe)
        auth = app.state.reviewer_auth
        with ThreadPoolExecutor(max_workers=8) as pool:
            tokens = list(pool.map(auth.login, [PASSWORD] * 8))
        assert len(set(tokens)) == 8
        assert all(auth.authenticated(token) for token in tokens)
        assert peak == 2
