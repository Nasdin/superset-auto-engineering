from dataclasses import replace

import httpx
import pytest
from app.automation.config import Settings
from app.automation.providers import ProviderError, Providers, UnknownEffect


def provider(handler):
    instance = Providers(replace(Settings(), github_token="test", slack_token="test"))
    instance.client.close()
    instance.client = httpx.Client(transport=httpx.MockTransport(handler))
    return instance


def test_malformed_successful_mutation_is_unknown_effect():
    p = provider(lambda req: httpx.Response(200, text="bad JSON"))
    with pytest.raises(UnknownEffect):
        p.comment(1, "body")
    with pytest.raises(ProviderError):
        p.gh("GET", "user")


@pytest.mark.parametrize("mutation", ["body", "issue_url"])
def test_github_readback_must_match_report_and_target(mutation):
    response = {
        "body": "exact report",
        "issue_url": "https://api.github.com/repos/Nasdin/superset/issues/1",
        "html_url": "https://github.com/Nasdin/superset/issues/1#issuecomment-123",
    }
    response[mutation] = "wrong"
    p = provider(lambda req: httpx.Response(200, json=response))
    with pytest.raises(ProviderError, match="does not match"):
        p.confirm_publication(
            {
                "provider": "github",
                "repository": "Nasdin/superset",
                "number": 1,
                "body": "exact report",
            },
            {"id": 123},
        )


def test_slack_gets_real_permalink_with_read_only_request():
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "channel": "C_DEMO",
                "permalink": "https://example.slack.com/archives/C_DEMO/p123456",
            },
        )

    p = provider(response)
    url = p.confirm_publication(
        {"provider": "slack", "channel": "C_DEMO"},
        {"channel": "C_DEMO", "ts": "123.456"},
    )
    assert url == "https://example.slack.com/archives/C_DEMO/p123456"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.path == "/api/chat.getPermalink"
    assert calls[0].url.params["message_ts"] == "123.456"


@pytest.mark.parametrize(
    "response",
    [
        {},
        None,
        [],
        {"ok": False, "error": "internal_error"},
        {"ok": False, "error": "fatal_error"},
        {"ok": True},
    ],
)
def test_slack_ambiguous_outcomes_are_never_definite_failures(response):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response)

    p = provider(handle)
    with pytest.raises(UnknownEffect):
        p.slack("report", "correlation", channel="C_DEMO")
    assert len(calls) == 1


def ready_pr(*, draft=True, sha="a" * 40):
    return {
        "node_id": "PR_test",
        "state": "open",
        "draft": draft,
        "head": {"sha": sha, "repo": {"full_name": "Nasdin/superset"}},
        "base": {"ref": "cognition-release-6.1", "repo": {"full_name": "Nasdin/superset"}},
        "html_url": "https://github.com/Nasdin/superset/pull/4",
    }


def test_ready_promotion_reads_back_and_reconciles_without_repeat_write():
    calls = []
    draft = True

    def handle(req):
        nonlocal draft
        calls.append(req.method)
        if req.method == "POST":
            assert req.url.path == "/graphql"
            draft = False
            return httpx.Response(200, json={"data": {"markPullRequestReadyForReview": {}}})
        return httpx.Response(200, json=ready_pr(draft=draft))

    p = provider(handle)
    assert p.mark_ready(4, "a" * 40)["draft"] is False
    assert p.mark_ready(4, "a" * 40)["sha"] == "a" * 40
    assert calls == ["GET", "POST", "GET", "GET"]


@pytest.mark.parametrize("field", ["sha", "repository", "base", "closed"])
def test_ready_promotion_refuses_changed_or_out_of_scope_pr(field):
    pr = ready_pr()
    if field == "sha":
        pr["head"]["sha"] = "b" * 40
    elif field == "repository":
        pr["head"]["repo"]["full_name"] = "apache/superset"
    elif field == "base":
        pr["base"]["ref"] = "master"
    else:
        pr["state"] = "closed"
    calls = []

    def handle(req):
        calls.append(req.method)
        return httpx.Response(200, json=pr)

    with pytest.raises(ProviderError, match="target changed"):
        provider(handle).mark_ready(4, "a" * 40)
    assert calls == ["GET"]


@pytest.mark.parametrize("response", [{}, {"errors": [{"message": "partial failure"}]}])
def test_ready_promotion_ambiguous_response_needs_reconciliation(response):
    p = provider(
        lambda req: httpx.Response(200, json=ready_pr() if req.method == "GET" else response)
    )
    with pytest.raises(UnknownEffect):
        p.mark_ready(4, "a" * 40)
