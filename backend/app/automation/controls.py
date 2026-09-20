"""Operator-only workflow controls; public schedules remain reviewable."""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .engine import Engine
from .pr_validation import PullRequestValidationService
from .providers import ProviderError
from .routes import IssueRequest, get_engine, operator
from .schedules import ScheduleConflict, ScheduleService

router = APIRouter(prefix="/api/live", tags=["workflow controls"])


class ManualRun(BaseModel):
    request_id: UUID


def require_execution(eng):
    if not (eng.settings.enabled and eng.settings.devin_key and eng.settings.github_token):
        raise HTTPException(409, "Execution is disabled or provider credentials are missing")


@router.get("/operator", dependencies=[Depends(operator)])
def operator_status():
    return {"authenticated": True}


@router.get("/automations")
def automations(eng: Engine = Depends(get_engine)):
    return ScheduleService(eng.settings, eng.store, eng.providers).overview()


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_seconds: int
    expected_updated: float


@router.post("/schedules/discovery", dependencies=[Depends(operator)])
def configure_schedule(body: ScheduleUpdate, eng: Engine = Depends(get_engine)):
    try:
        return ScheduleService(eng.settings, eng.store, eng.providers).configure(
            body.enabled, body.interval_seconds, body.expected_updated
        )
    except ScheduleConflict as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/scan", dependencies=[Depends(operator)])
def scan(body: ManualRun, eng: Engine = Depends(get_engine)):
    require_execution(eng)
    try:
        return ScheduleService(eng.settings, eng.store, eng.providers).run_now(str(body.request_id))
    except ScheduleConflict as error:
        raise HTTPException(409, str(error)) from None
    except ProviderError as error:
        raise HTTPException(502, str(error)) from None


@router.post("/validate", dependencies=[Depends(operator)])
def validate_pr(body: IssueRequest, eng: Engine = Depends(get_engine)):
    require_execution(eng)
    try:
        return PullRequestValidationService(eng.settings, eng.store, eng.providers).accept(
            body.number, "manual"
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except ProviderError as error:
        raise HTTPException(502, str(error)) from None


@router.post("/jobs/{job_id}/resume", dependencies=[Depends(operator)])
def resume_job(job_id: str, body: ManualRun, eng: Engine = Depends(get_engine)):
    """Resume the same provider session once; an ambiguous message is never resent."""
    from .providers import UnknownEffect
    from .validation import ValidationService

    require_execution(eng)
    job = eng.store.get(job_id)
    if not job or not job.get("session_id"):
        raise HTTPException(404, "No provider session for this job")
    key = f"resume:{job_id}:{body.request_id}"
    if prior := eng.store.recall(key):
        return prior
    if job["state"] != "needs_attention":
        raise HTTPException(409, "Only paused sessions may be resumed")
    try:
        session = eng.providers.session(job["session_id"])
        if f"cognition-job:{job_id}" not in session.get("tags", []):
            raise HTTPException(409, "Session correlation does not match")
        if session.get("is_archived") or session.get("status") in {"exit", "error"}:
            raise HTTPException(409, "Session cannot resume; inspect it in Devin")
        if job["kind"] == "validation" and not ValidationService(
            eng.settings, eng.store, eng.providers
        ).is_current(job):
            raise HTTPException(409, "Candidate changed; a new validation is required")
        # Claim the intent across API processes before the paid provider mutation.
        with eng.store.connect() as c:
            c.lock()
            changed = c.execute(
                "UPDATE jobs SET state='unknown_effect',error='Resume requested; awaiting provider readback' "
                "WHERE id=:id AND state='needs_attention'",
                {"id": job_id},
            ).rowcount
        if not changed:
            raise HTTPException(409, "Another operation is already handling this session")
        intent = {"status": "unknown_effect", "job_id": job_id}
        eng.store.remember(key, intent)
        eng.store.audit(job_id, "resume_requested", {"request_id": str(body.request_id)})
        observed = eng.providers.devin(
            "POST",
            f"sessions/{job['session_id']}/messages",
            json={
                "message": "Continue this assigned task in the same session and exact repository scope. "
                "Preserve existing progress and provider spending limits. Do not create child sessions, "
                "merge, deploy or change budgets. Report a concrete blocker if you cannot continue. "
                "Only claim checks and evidence you actually executed. Return the required structured final handoff. "
                f"Resume correlation: {body.request_id}."
            },
        )
        if not isinstance(observed, dict) or observed.get("session_id") != job["session_id"]:
            raise UnknownEffect("Resume response identity is not confirmed")
        eng.store.update(job_id, state="running", error=None, started=time.time(), next_poll=0)
        receipt = {"status": "resumed", "job_id": job_id, "session_url": job["session_url"]}
        eng.store.remember(key, receipt)
        return receipt
    except ProviderError as error:
        if eng.store.recall(key):
            eng.store.update(job_id, state="needs_attention", error=str(error))
            eng.store.remember(key, {"status": "rejected", "job_id": job_id, "error": str(error)})
        raise HTTPException(502, str(error)) from None
    except UnknownEffect as error:
        eng.store.update(job_id, state="unknown_effect", error=str(error))
        raise HTTPException(
            409, "Resume outcome is uncertain; inspect Devin before retrying"
        ) from None
