from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import httpx
import pytest
from app.analytics.embedding import Selection, SupersetClient


def test_selection_scope_and_comparison_dates():
    result = Selection(end=date(2026, 8, 31)).resolved("Nasdin/superset")
    assert result["baseline_end"] == "2026-02-28"
    for selection in (
        Selection(repository="attacker/repo"),
        Selection(end=date(2030, 1, 1)),
        Selection(comparison="custom"),
    ):
        with pytest.raises(ValueError):
            selection.resolved("Nasdin/superset")


def test_guest_tokens_use_only_fixed_dashboard_and_server_selected_scope():
    calls = []

    def provider(request):
        import json

        calls.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("/guest_token/"):
            assert request.headers["Authorization"] == "Bearer service-secret"
            assert "Cookie" not in request.headers
        return httpx.Response(
            200,
            json={"access_token": "service-secret"}
            if request.url.path.endswith("/login")
            else {"token": "guest-only"},
        )

    with httpx.Client(
        base_url="http://superset:8088/bi", transport=httpx.MockTransport(provider)
    ) as http:
        client = SupersetClient("http://superset:8088/bi", "password", client=http)
        assert client.guest_token("fixed-dashboard", "a" * 64) == "guest-only"
        assert client.guest_token("fixed-dashboard", "b" * 64) == "guest-only"
    assert len(calls) == 3
    assert calls[0][0] == "/bi/api/v1/security/login"
    assert calls[-1][1]["resources"] == [{"type": "dashboard", "id": "fixed-dashboard"}]
    assert calls[-1][1]["rls"] == [{"clause": "selection_id = '" + "b" * 64 + "'"}]


@pytest.mark.parametrize("status", [401, 403, 500])
def test_issuer_retry_is_bounded_and_only_for_expired_authentication(status):
    paths = []

    def provider(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"access_token": "new-issuer"})
        return httpx.Response(status)

    with httpx.Client(base_url="http://superset", transport=httpx.MockTransport(provider)) as http:
        client = SupersetClient("http://superset", "password", client=http)
        with pytest.raises(httpx.HTTPStatusError):
            client.guest_token("dashboard", "a" * 64)
        assert not client.lock.locked()
    assert len(paths) == (4 if status == 401 else 2)


def test_expired_cached_issuer_is_renewed_without_changing_guest_scope():
    payloads = []
    logins = []

    def provider(request):
        import json

        if request.url.path.endswith("/login"):
            logins.append(True)
            return httpx.Response(200, json={"access_token": f"issuer-{len(logins)}"})
        payloads.append(json.loads(request.content))
        if len(payloads) == 2:
            return httpx.Response(401)
        return httpx.Response(200, json={"token": "guest"})

    with httpx.Client(base_url="http://superset", transport=httpx.MockTransport(provider)) as http:
        client = SupersetClient("http://superset", "password", client=http)
        assert client.guest_token("dashboard", "a" * 64) == "guest"
        assert client.guest_token("dashboard", "b" * 64) == "guest"
        assert payloads[1] == payloads[2]
        assert len(logins) == 2
        with pytest.raises(ValueError, match="selection"):
            client.guest_token("dashboard", "' OR 1=1 --")


def test_concurrent_guest_request_exhausts_issuer_wait_without_another_provider_call():
    entered = Event()
    release = Event()
    calls = []

    def provider(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            entered.set()
            assert release.wait(timeout=10), "Test must release the occupied issuer"
            return httpx.Response(200, json={"access_token": "issuer"})
        return httpx.Response(200, json={"token": "guest"})

    with httpx.Client(base_url="http://superset", transport=httpx.MockTransport(provider)) as http:
        client = SupersetClient("http://superset", "password", client=http)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(client.guest_token, "dashboard", "a" * 64)
            try:
                assert entered.wait(timeout=2)
                second = executor.submit(client.guest_token, "dashboard", "b" * 64)
                with pytest.raises(httpx.PoolTimeout, match="issuer is busy"):
                    second.result(timeout=7)
                assert calls == ["/api/v1/security/login"]
            finally:
                release.set()
            assert first.result(timeout=2) == "guest"
            assert client.guest_token("dashboard", "b" * 64) == "guest"
            assert not client.lock.locked()


def test_superset_http_client_bounds_connection_and_read_waits():
    client = SupersetClient("http://superset", "password")
    try:
        assert client.client.timeout == httpx.Timeout(30, connect=5, pool=5, write=5)
    finally:
        client.close()
