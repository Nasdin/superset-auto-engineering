"""Provider-owned handoffs and public, immutable copies for PR reviewers."""

import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .links import safe_link
from .providers import ProviderError
from .redaction import provider_secrets, redact_text


def attachment_records(value):
    return value.get("items", value.get("attachments", [])) if isinstance(value, dict) else value


def provider_attachment_index(attachments):
    """Bounded context for the owning agent, never an inferred artifact mapping."""
    return [
        {key: item.get(key, "") for key in ("name", "url", "content_type")}
        for item in attachments
        if item.get("source") == "devin"
        and item.get("attachment_id")
        and isinstance(item.get("url"), str)
        and safe_link(item["url"])
    ][:24]


def unconfirmed_evidence_urls(result, attachments):
    known = {item["url"] for item in provider_attachment_index(attachments)}
    references = [item.get("url") for item in result.get("artifacts", [])]
    references += [item.get("evidence_url") for item in result.get("api_requests", [])]
    references += [
        (result.get(key) or {}).get("report_url") for key in ("coverage", "test_results")
    ]
    return sorted({url for url in references if isinstance(url, str) and url and url not in known})


def complete_handoff(providers, result, attachments):
    """Legacy sessions have immutable output schemas; accept their attached v2 report."""
    if result.get("evidence_version") == 2:
        return result
    mentioned = {a.get("url") for a in result.get("artifacts", [])}
    reports = [
        a
        for a in attachments
        if a.get("source") == "devin"
        and a.get("name") == "evidence-report.json"
        and a.get("url") in mentioned
    ]
    if not reports:
        return result
    if len(reports) != 1:
        raise ValueError("Ambiguous final evidence report; validator must identify one attachment")
    content, mime = providers.attachment_content(reports[0], limit=2_000_000)
    if mime.split(";")[0] != "application/json":
        raise ValueError("Evidence report is not JSON")
    report = json.loads(content)
    if not isinstance(report, dict) or report.get("candidate_sha") != result.get("candidate_sha"):
        raise ValueError("Attached evidence report has a different candidate")
    if (
        result.get("task_complete") is not True
        or report.get("task_complete") is not True
        or report.get("passed") != result.get("passed")
        or str(report.get("blocker", "")).strip() != str(result.get("blocker", "")).strip()
    ):
        raise ValueError("Attached report conflicts with the final session handoff")
    return {**report, "handoff_attachment_id": reports[0]["attachment_id"]}


class EvidenceArchive:
    """Serve only approved media/text types, never arbitrary agent HTML or paths."""

    def __init__(self, settings, providers):
        self.settings, self.providers = settings, providers
        self.directory = settings.artifacts / "published"

    def publish(self, artifacts, attachments):
        if not self.settings.evidence_public_url:
            return artifacts
        known = {a["url"]: a for a in attachments if a.get("source") == "devin"}
        self.directory.mkdir(parents=True, exist_ok=True)
        if len(artifacts) > 24:
            raise ProviderError(
                "Too many artifacts to publish", category="invalid_artifact", retryable=False
            )
        result, total_bytes = [], 0
        for artifact in artifacts:
            content, mime = self.providers.attachment_content(known[artifact["url"]])
            total_bytes += len(content)
            if total_bytes > 80_000_000:
                raise ProviderError(
                    "Evidence archive exceeds 80 MB", category="invalid_artifact", retryable=False
                )
            mime = mime.split(";")[0].lower()
            if artifact["kind"] == "screenshot":
                if mime != "image/png" or not content.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ProviderError(
                        "Public screenshots must be PNG files",
                        category="invalid_artifact",
                        retryable=False,
                    )
                extension = "png"
            elif artifact["kind"] == "video":
                if mime != "video/mp4" or content[4:8] != b"ftyp":
                    raise ProviderError(
                        "Public recordings must be MP4 files",
                        category="invalid_artifact",
                        retryable=False,
                    )
                extension = "mp4"
            else:
                if not (mime.startswith("text/") or mime == "application/json"):
                    raise ProviderError(
                        "Public execution evidence must be text or JSON",
                        category="invalid_artifact",
                        retryable=False,
                    )
                try:
                    content = redact_text(
                        content.decode("utf-8"), provider_secrets(self.settings)
                    ).encode()
                except UnicodeError:
                    raise ProviderError(
                        "Execution evidence is not UTF-8 text",
                        category="invalid_artifact",
                        retryable=False,
                    ) from None
                extension = "txt"
            digest = hashlib.sha256(content).hexdigest()
            name = f"{digest}.{extension}"
            destination = self.directory / name
            # Atomic replacement, content-addressed; retries cannot create another URL.
            with NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as temporary:
                temporary.write(content)
            Path(temporary.name).replace(destination)
            result.append(
                {
                    **artifact,
                    "public_url": f"{self.settings.evidence_public_url}/public-evidence/{name}",
                    "content_sha256": digest,
                }
            )
        return result


def public_evidence(directory: Path, name: str):
    if not re.fullmatch(r"[a-f0-9]{64}\.(png|mp4|txt)", name):
        raise HTTPException(404, "Evidence not found")
    path = directory / "published" / name
    if not path.is_file():
        raise HTTPException(404, "Evidence not found")
    mime = {"png": "image/png", "mp4": "video/mp4", "txt": "text/plain"}[name.rsplit(".", 1)[1]]
    return FileResponse(
        path,
        media_type=mime,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
