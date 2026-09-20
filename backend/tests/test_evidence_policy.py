import pytest
from app.automation.evidence import assess_evidence
from app.automation.links import safe_link
from app.automation.reports import ReleaseReportBuilder
from test_automation import SHA, FakeProvider, result


def assess(payload=None, attachments=None):
    return assess_evidence(
        candidate_sha=SHA,
        validator_session="validator",
        implementation_sessions=["implementer"],
        result=result() if payload is None else payload,
        attachments=FakeProvider().attachments("validator") if attachments is None else attachments,
    )


@pytest.mark.parametrize("field,value", [("checks", {}), ("checks", [None]), ("artifacts", "bad")])
def test_malformed_evidence_is_rejected(field, value):
    payload = result()
    payload[field] = value
    with pytest.raises(ValueError):
        assess(payload)


def test_duplicate_checks_do_not_satisfy_gate():
    payload = result()
    payload["checks"].append(payload["checks"][0])
    assert not assess(payload).passed


def test_attachment_ids_must_be_distinct():
    attachments = FakeProvider().attachments("validator")
    for item in attachments:
        item["attachment_id"] = "same-file"
    assert not assess(attachments=attachments).passed


@pytest.mark.parametrize(
    "url",
    [
        None,
        1,
        "javascript:alert(1)",
        "http://example.com",
        "https://user:password@example.com",
        "https://example.com/\nscript",
        "https://example.com/[x](evil)",
        "https://[broken",
    ],
)
def test_unsafe_links_are_rejected(url):
    assert not safe_link(url)


def test_report_preserves_markdown_table_and_escapes_agent_text():
    payload = result()
    payload["summary"] = "<script>@everyone [click](evil)</script>"
    payload["checks"][0]["command"] = "`|<img>\n@all"
    report = ReleaseReportBuilder().build(
        {"candidate_sha": SHA, "session_url": "https://app.devin.ai/sessions/validator"},
        payload,
        "review_ready",
    )
    assert "|---|---|---|\n|" in report
    assert "<script>" not in report
    assert "<img>" not in report
    assert "@everyone" not in report
    assert "@all" not in report
    assert "\\[click\\]" in report


@pytest.mark.parametrize("field", ["api_requests", "coverage", "test_results"])
def test_missing_execution_evidence_blocks_release(field):
    payload = result()
    payload.pop(field)
    assert not assess(payload).passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("lines_total", 0),
        ("lines_covered", 101),
        ("branches_covered", 21),
        ("lines_covered", True),
        ("lines_total", float("nan")),
    ],
)
def test_coverage_counts_are_measured_and_valid(field, value):
    payload = result()
    payload["coverage"][field] = value
    assert not assess(payload).passed


def test_api_failure_and_unconfirmed_transcript_cannot_pass():
    payload = result()
    payload["api_requests"][0]["actual_status"] = 500
    assert not assess(payload).passed
    payload = result()
    payload["api_requests"][0]["evidence_url"] = "https://example.com/invented"
    assert not assess(payload).passed


def test_report_includes_curl_response_coverage_and_embedded_superset_image():
    report = ReleaseReportBuilder().build(
        {"candidate_sha": SHA, "session_url": "https://app.devin.ai/sessions/validator"},
        result(),
        "review_ready",
    )
    assert "curl -X POST" in report and "observed HTTP 200" in report
    assert "80/100 (80.0%)" in report and "9 passed" in report
    assert "![Superset running" in report
    assert '"value":1' in report


def test_execution_text_is_redacted_before_report_and_durable_storage():
    from app.automation.redaction import sanitize

    payload = result()
    payload["summary"] = "Authorization: Bearer secret123"
    payload["api_requests"][0]["curl"] = (
        "curl -H 'Authorization: Bearer SECRET_TOKEN' -H 'Cookie: session=SESSION_SECRET' http://localhost:8088/api/v1/chart/"
    )
    payload["api_requests"][0]["response_excerpt"] = (
        '{"access_token":"TOKEN_SECRET","password":"PASSWORD_SECRET"}'
    )
    payload["checks"][0]["detail"] = "https://user:URL_SECRET@localhost/api/?api_key=QUERY_SECRET"
    clean = sanitize(payload)
    import json

    report = ReleaseReportBuilder().build(
        {"candidate_sha": SHA, "session_url": "https://app.devin.ai/sessions/validator"},
        clean,
        "validation_failed",
    )
    for secret in [
        "secret123",
        "SECRET_TOKEN",
        "SESSION_SECRET",
        "TOKEN_SECRET",
        "PASSWORD_SECRET",
        "URL_SECRET",
        "QUERY_SECRET",
    ]:
        assert secret not in json.dumps(clean) and secret not in report
    assert "[REDACTED]" in report


@pytest.mark.parametrize(
    "url", ["http://localhost:8088/api/v1/security/login", "http://localhost:8088/api/health"]
)
def test_authentication_or_health_only_is_not_functional_api_evidence(url):
    payload = result()
    payload["api_requests"][0]["url"] = url
    assert not assess(payload).passed


@pytest.mark.parametrize(
    "option",
    [
        "-u alice:PRIVATE",
        "--user=alice:PRIVATE",
        "-b session=PRIVATE",
        "--cookie 'session=PRIVATE'",
        "-Ualice:PRIVATE",
        "-H 'X-CSRFToken: PRIVATE'",
    ],
)
def test_curl_credential_options_are_redacted(option):
    from app.automation.redaction import sanitize

    assert "PRIVATE" not in str(
        sanitize({"curl": f"curl {option} http://localhost:8088/api/v1/chart/"})
    )
