import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from .config import Settings
from .store import Store
from .engine import Engine
from .providers import Providers, ProviderError

router = APIRouter(prefix="/api/live", tags=["automation"])
settings = Settings()


def engine():
    return Engine(settings, Store(settings.database), Providers(settings))


def operator(authorization: str = Header(default="")):
    expected = "Bearer " + settings.operator_token
    if not settings.operator_token or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Local operator authentication required")


@router.get("/overview")
def overview():
    db = Store(settings.database)
    jobs = db.jobs()
    return {
        "mode": "live",
        "enabled": settings.enabled,
        "repository": settings.repo,
        "branch": settings.branch,
        "connections": {
            "devin": bool(settings.devin_key),
            "github": bool(settings.github_token),
            "slack": bool(settings.slack_token and settings.slack_channel),
        },
        "limits": {
            "max_acu_per_session": settings.max_acu,
            "max_sessions_total": settings.max_sessions,
            "scan_interval_seconds": settings.scan_interval,
        },
        "worker": db.recall("worker_status", {}),
        "jobs": jobs,
        "publications": db.publications(),
        "memory": db.recall("repository_lessons", []),
        "last_scan": db.recall("last_scan", {}),
        "metrics": {
            "sessions": sum(bool(j["session_id"]) for j in jobs),
            "acu": sum(j["acu"] for j in jobs),
            "review_ready": sum(j["state"] == "review_ready" for j in jobs),
            "attention": sum(
                j["state"]
                in ["blocked", "needs_attention", "unknown_effect", "validation_failed"]
                for j in jobs
            ),
        },
    }


class IssueRequest(BaseModel):
    number: int = Field(gt=0)


@router.post("/issues", dependencies=[Depends(operator)])
def submit(body: IssueRequest):
    try:
        return engine().accept_issue(body.number, "operator")
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except ProviderError as e:
        raise HTTPException(502, str(e)) from None


@router.post("/scan", dependencies=[Depends(operator)])
def scan():
    return engine().schedule_scan()


@router.post("/webhooks/github")
async def github_event(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    if not settings.webhook_secret:
        raise HTTPException(503, "GitHub webhook is not configured")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "Payload too large")
    signature = (
        "sha256="
        + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(signature, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")
    if not x_github_delivery or len(x_github_delivery) > 200:
        raise HTTPException(400, "Delivery ID required")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Invalid JSON") from None
    if (
        payload.get("repository", {}).get("full_name", "").lower()
        != settings.repo.lower()
    ):
        raise HTTPException(403, "Repository not allowed")
    if (
        payload.get("sender", {}).get("login", "").lower()
        != settings.allowed_actor.lower()
    ):
        raise HTTPException(403, "Actor not allowed")
    if x_github_event != "issues" or payload.get("action") not in [
        "opened",
        "labeled",
        "reopened",
    ]:
        return {"status": "ignored"}
    if settings.label not in [
        x["name"] for x in payload.get("issue", {}).get("labels", [])
    ]:
        return {"status": "ignored", "reason": "repair label missing"}
    eng = engine()
    with eng.db.connect() as c:
        if c.execute(
            "SELECT 1 FROM deliveries WHERE id=?", (x_github_delivery,)
        ).fetchone():
            return {"status": "duplicate"}
    try:
        job = eng.accept_issue(payload["issue"]["number"], "github_webhook")
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from None
    with eng.db.connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO deliveries VALUES(?,?)",
            (x_github_delivery, time.time()),
        )
    return {"status": "accepted", "job_id": job["id"]}


class Reconcile(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{5,100}$")


@router.post("/jobs/{job_id}/reconcile", dependencies=[Depends(operator)])
def reconcile(job_id: str, body: Reconcile):
    eng = engine()
    job = eng.db.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["state"] not in ["unknown_effect", "needs_attention"]:
        raise HTTPException(
            409, "Only uncertain or attention-required jobs may be reconciled"
        )
    session = eng.p.session(body.session_id)
    if f"cognition-job:{job_id}" not in session.get("tags", []):
        raise HTTPException(409, "Session lacks the matching correlation tag")
    eng.db.update(
        job_id,
        state="running",
        session_id=body.session_id,
        session_url=session["url"],
        started=job.get("started") or session["created_at"],
        error=None,
        next_poll=0,
    )
    eng.db.audit(job_id, "operator_reconciled", {"session_id": body.session_id})
    return eng.db.get(job_id)


@router.post("/jobs/{job_id}/resume-integration", dependencies=[Depends(operator)])
def resume_integration(job_id: str):
    eng = engine()
    job = eng.db.get(job_id)
    if not job or job["kind"] != "integration":
        raise HTTPException(404, "Integration job not found")
    if job["state"] not in ["unknown_effect", "needs_attention", "blocked"]:
        raise HTTPException(409, "Job is not stopped")
    # assemble_candidate reads the branch, merge parents and existing PR before writes.
    eng.db.update(job_id, state="queued", lease_until=0, error=None)
    eng.db.audit(job_id, "operator_requested_integration_readback", {})
    return {"status": "queued_for_github_reconciliation"}
