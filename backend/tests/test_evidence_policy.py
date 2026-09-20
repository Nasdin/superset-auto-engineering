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
