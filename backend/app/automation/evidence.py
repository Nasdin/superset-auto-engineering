"""Pure, fail-closed evidence policy; does not fetch agent-selected URLs."""

from dataclasses import dataclass
from typing import Any

from .links import safe_link

REQUIRED_CHECKS = {"services", "database", "browser", "regression"}
REQUIRED_ARTIFACTS = {"screenshot", "video", "logs", "tests"}


@dataclass(frozen=True)
class EvidenceAssessment:
    passed: bool
    artifacts: list[dict[str, Any]]
    failures: tuple[str, ...]


def records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def media_matches(kind: str, content_type: str) -> bool:
    mime = content_type.lower().split(";")[0]
    if kind == "screenshot":
        return mime.startswith("image/")
    if kind == "video":
        return mime.startswith("video/")
    return kind in {"logs", "tests"} and (
        mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/zip"}
    )


def assess_evidence(
    *,
    candidate_sha: str,
    validator_session: str,
    implementation_sessions: list[str | None],
    result: dict[str, Any],
    attachments: Any,
) -> EvidenceAssessment:
    if isinstance(attachments, dict):
        attachments = attachments.get("items", attachments.get("attachments", []))
    known = {
        item["url"]: item
        for item in records(attachments, "Attachments")
        if item.get("source") == "devin"
        and isinstance(item.get("url"), str)
        and isinstance(item.get("attachment_id"), str)
        and item["attachment_id"]
    }
    checks = records(result.get("checks", []), "Checks")
    artifacts = records(result.get("artifacts", []), "Artifacts")
    failures = []
    if result.get("candidate_sha") != candidate_sha:
        failures.append("Evidence SHA does not match the candidate")
    if result.get("passed") is not True or str(result.get("blocker", "")).strip():
        failures.append("Validator reported failure or an unresolved blocker")
    names = [check.get("name") for check in checks]
    if (
        any(not isinstance(name, str) for name in names)
        or len(set(names)) != len(names)
        or not REQUIRED_CHECKS.issubset(names)
        or any(
            check.get("passed") is not True
            or not isinstance(check.get("command"), str)
            or not check["command"].strip()
            for check in checks
        )
    ):
        failures.append("Mandatory checks are missing, duplicated, or failing")
    if (
        not validator_session
        or not implementation_sessions
        or any(not session or session == validator_session for session in implementation_sessions)
    ):
        failures.append("Validator independence is not established")
    verified = []
    for artifact in artifacts:
        url = artifact.get("url")
        meta = known.get(url, {}) if isinstance(url, str) else {}
        kind = artifact.get("kind")
        name = artifact.get("name")
        mime = meta.get("content_type")
        if (
            meta
            and safe_link(url)
            and isinstance(name, str)
            and name.strip()
            and isinstance(kind, str)
            and isinstance(mime, str)
            and media_matches(kind, mime)
        ):
            verified.append({**artifact, "attachment_id": meta["attachment_id"]})
    if (
        len(verified) != len(artifacts)
        or not REQUIRED_ARTIFACTS.issubset(a["kind"] for a in verified)
        or len({a["url"] for a in verified}) != len(verified)
        or len({a["attachment_id"] for a in verified}) != len(verified)
    ):
        failures.append("Distinct provider-confirmed artifacts are missing or invalid")
    return EvidenceAssessment(not failures, verified, tuple(failures))
