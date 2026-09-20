import json
from dataclasses import replace

import httpx
import pytest
from app.automation.artifacts import EvidenceArchive, complete_handoff, public_evidence
from app.automation.config import Settings
from app.automation.providers import ProviderError, Providers
from fastapi import HTTPException

META = {
    "attachment_id": "e5b6d670-4564-4e9f-9075-5c4f3066367c",
    "name": "log.txt",
    "url": "https://app.devin.ai/attachments/id/log.txt",
    "source": "devin",
}


def test_download_uses_provider_identity_and_never_forwards_key():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "api.devin.ai":
            return httpx.Response(
                307,
                headers={
                    "location": "https://bucket.s3.us-west-2.amazonaws.com/evidence?signature=secret"
                },
            )
        return httpx.Response(200, content=b"actual logs", headers={"content-type": "text/plain"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = Providers(Settings(devin_key="private-key"), client=client)
        assert provider.attachment_content(META) == (b"actual logs", "text/plain")
    assert requests[0].headers["authorization"] == "Bearer private-key"
    assert not requests[1].headers.get("authorization")
    assert META["attachment_id"] in requests[0].url.path


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/private",
        "https://example.com/private",
        "https://bucket.s3.amazonaws.com:444/private",
        "https://user:pass@bucket.s3.amazonaws.com/private",
    ],
)
def test_download_rejects_non_provider_redirect(location):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(307, headers={"location": location}))
    ) as client:
        with pytest.raises(ProviderError):
            Providers(Settings(), client=client).attachment_content(META)


def test_download_is_bounded_and_errors_do_not_include_signed_links():
    def handle(request):
        if request.url.host == "api.devin.ai":
            return httpx.Response(
                307, headers={"location": "https://bucket.s3.amazonaws.com/file?secret=hidden"}
            )
        return httpx.Response(200, content=b"too much content")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError, match="size limit") as error:
            Providers(Settings(), client=client).attachment_content(META, limit=2)
        assert "hidden" not in str(error.value)


def test_archive_is_immutable_redacted_and_does_not_serve_arbitrary_files(tmp_path):
    settings = replace(
        Settings(),
        artifacts=tmp_path,
        evidence_public_url="https://review.example",
        devin_key="secret-provider-value",
    )

    class Provider:
        def attachment_content(self, *_):
            return (
                b"curl -H 'Authorization: Bearer abc123'\nsecret-provider-value\nresult=5",
                "text/plain",
            )

    archive = EvidenceArchive(settings, Provider())
    artifact = {"kind": "api", "name": "log.txt", "url": META["url"]}
    first = archive.publish([artifact], [META])[0]
    assert archive.publish([artifact], [META])[0] == first
    name = first["public_url"].rsplit("/", 1)[1]
    response = public_evidence(tmp_path, name)
    text = response.path.read_text()
    assert "secret-provider-value" not in text and "abc123" not in text
    assert "result=5" in text
    assert response.media_type == "text/plain"
    assert response.headers["x-content-type-options"] == "nosniff"
    for bad in ["../runtime.env", "a" * 64 + ".html", "a" * 64 + ".txt"]:
        with pytest.raises(HTTPException):
            public_evidence(tmp_path, bad)


def test_legacy_report_must_be_owned_mentioned_and_same_sha():
    meta = {**META, "name": "evidence-report.json"}
    result = {
        "candidate_sha": "a" * 40,
        "task_complete": True,
        "passed": True,
        "artifacts": [{"url": meta["url"]}],
    }

    class Provider:
        report = {
            "candidate_sha": "a" * 40,
            "evidence_version": 2,
            "task_complete": True,
            "passed": True,
        }

        def attachment_content(self, *_, **kwargs):
            return json.dumps(self.report).encode(), "application/json"

    provider = Provider()
    assert complete_handoff(provider, result, [meta])["evidence_version"] == 2
    assert complete_handoff(provider, result, [{**meta, "source": "user"}]) == result
    provider.report["candidate_sha"] = "b" * 40
    with pytest.raises(ValueError, match="different candidate"):
        complete_handoff(provider, result, [meta])


def test_secret_formats_in_service_logs_are_redacted():
    from app.automation.redaction import redact_text

    source = "postgresql+psycopg://app:database-password@db/test\nSUPERSET_SECRET_KEY=flask-secret\nPOSTGRES_PASSWORD=database-password\nMYSQL_ROOT_PASSWORD='root-secret'"
    redacted = redact_text(source)
    for secret in ["database-password", "flask-secret", "root-secret"]:
        assert secret not in redacted


def test_report_cannot_erase_failed_final_verdict():
    meta = {**META, "name": "evidence-report.json"}
    final = {
        "task_complete": True,
        "passed": False,
        "blocker": "Broken endpoint",
        "candidate_sha": "a" * 40,
        "artifacts": [{"url": meta["url"]}],
    }

    class Provider:
        def attachment_content(self, *args, **kwargs):
            return json.dumps(
                {**final, "passed": True, "blocker": "", "evidence_version": 2}
            ).encode(), "application/json"

    with pytest.raises(ValueError, match="conflicts"):
        complete_handoff(Provider(), final, [meta])


def test_corrected_handoff_has_new_idempotent_publication_receipt(tmp_path):
    from app.automation.outbox import PublicationOutbox
    from app.automation.store import Store

    settings = replace(Settings(), database=str(tmp_path / "ledger.db"))
    store = Store(settings.database)
    outbox = PublicationOutbox(settings, store, None)
    outbox.publish("job", 4, "original failed gate", validation={"job_id": "job"})
    revised = {"job_id": "job", "revision": "provider-attachment-id"}
    outbox.publish("job", 4, "corrected evidence", validation=revised)
    outbox.publish("job", 4, "corrected evidence", validation=revised)
    with store.connect() as c:
        rows = c.execute("SELECT key FROM publications").fetchall()
    assert {row["key"] for row in rows} == {"github:job:4", "github:job:4:provider-attachment-id"}
