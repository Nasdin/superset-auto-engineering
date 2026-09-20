from datetime import date

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
