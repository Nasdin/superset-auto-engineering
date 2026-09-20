import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .dependencies import DependencyService
from .engine import Engine
from .learning import LearningService, workflow_lane
from .patches import PatchService
from .pr_validation import VALIDATE_LABEL, PullRequestValidationService
from .providers import ProviderError

router = APIRouter(prefix="/api/live", tags=["automation"])


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_settings(engine: Engine = Depends(get_engine)) -> Settings:
    return engine.settings


def operator(authorization: str = Header(default=""), settings: Settings = Depends(get_settings)):
    expected = "Bearer " + settings.operator_token
    if not settings.operator_token or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Local operator authentication required")


@router.get("/overview")
def overview(eng: Engine = Depends(get_engine)):
    db = eng.store
    settings = eng.settings
    jobs = db.jobs()
    return {
        "mode": "live",
        "enabled": settings.enabled,
        "repository": settings.repo,
        "branch": settings.branch,
        "dependabot_enabled": settings.dependabot_enabled,
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
        "jobs": [{**job, "lane": workflow_lane(job, db)} for job in jobs],
        "publications": db.publications(),
        "memory": db.recall("repository_lessons", []),
        "last_scan": db.recall("last_scan", {}),
        "metrics": db.metrics(),
    }


class IssueRequest(BaseModel):
    number: int = Field(gt=0)


@router.post("/issues", dependencies=[Depends(operator)])
def submit(body: IssueRequest, eng: Engine = Depends(get_engine)):
    try:
        return eng.accept_issue(body.number, "operator")
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except ProviderError as e:
        raise HTTPException(502, str(e)) from None


@router.post("/scan", dependencies=[Depends(operator)])
def scan(eng: Engine = Depends(get_engine)):
    return eng.schedule_scan()


class WebhookRepository(BaseModel):
    full_name: str


class WebhookSender(BaseModel):
    login: str


class WebhookLabel(BaseModel):
    name: str


class WebhookIssue(BaseModel):
    number: int = Field(gt=0)
    labels: list[WebhookLabel] = Field(default_factory=list)


class WebhookHead(BaseModel):
    sha: str = Field(pattern=r"^[a-f0-9]{40}$")


class WebhookPullRequest(BaseModel):
    number: int = Field(gt=0)
    head: WebhookHead


class WebhookEnvelope(BaseModel):
    repository: WebhookRepository
    sender: WebhookSender
    action: str = ""
    issue: WebhookIssue | None = None
    pull_request: WebhookPullRequest | None = None


@router.post("/webhooks/github")
async def github_event(
    request: Request,
    eng: Engine = Depends(get_engine),
    x_hub_signature_256: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    settings = eng.settings
    if not settings.webhook_secret:
        raise HTTPException(503, "GitHub webhook is not configured")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1_000_000:
            raise HTTPException(413, "Payload too large")
    signature = (
        "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(signature, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")
    if not x_github_delivery or len(x_github_delivery) > 200:
        raise HTTPException(400, "Delivery ID required")
    try:
        payload = WebhookEnvelope.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Invalid webhook payload") from None
    if payload.repository.full_name.lower() != settings.repo.lower():
        raise HTTPException(403, "Repository not allowed")
    if x_github_event == "pull_request":
        if payload.action not in {
            "opened",
            "reopened",
            "ready_for_review",
            "synchronize",
            "labeled",
        }:
            return {"status": "ignored"}
        if payload.pull_request is None:
            raise HTTPException(422, "Pull request is required")
        try:
            pr = await run_in_threadpool(eng.providers.pr, payload.pull_request.number)
            if VALIDATE_LABEL in [x.get("name") for x in pr.get("labels", [])] or any(
                j["pr_number"] == payload.pull_request.number
                and j["kind"] in {"repair", "integration"}
                for j in eng.store.operational_jobs()
            ):
                if eng.store.has_delivery(x_github_delivery):
                    return {"status": "duplicate"}
                job = await run_in_threadpool(
                    PullRequestValidationService(settings, eng.store, eng.providers).accept,
                    payload.pull_request.number,
                    "pr_validation_webhook",
                    payload.pull_request.head.sha,
                )
                eng.store.record_delivery(x_github_delivery)
                return {
                    "status": job.get("status", "accepted"),
                    "job_id": job.get("id"),
                    "reason": job.get("reason"),
                }
            service = (
                PatchService
                if pr.get("user", {}).get("login", "").lower() == settings.allowed_actor.lower()
                else DependencyService
            )(settings, eng.store, eng.providers)
            return await run_in_threadpool(
                service.webhook,
                payload.pull_request.number,
                x_github_delivery,
                payload.pull_request.head.sha,
            )
        except ValueError as error:
            return {"status": "ignored", "reason": str(error)}
        except ProviderError as error:
            raise HTTPException(502, str(error)) from None
    if payload.sender.login.lower() != settings.allowed_actor.lower():
        raise HTTPException(403, "Actor not allowed")
    if x_github_event != "issues" or payload.action not in [
        "opened",
        "labeled",
        "reopened",
    ]:
        return {"status": "ignored"}
    if payload.issue is None:
        raise HTTPException(422, "Issue is required for issue events")
    if settings.label not in [label.name for label in payload.issue.labels]:
        return {"status": "ignored", "reason": "repair label missing"}
    try:
        return await run_in_threadpool(eng.accept_webhook, payload.issue.number, x_github_delivery)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except ProviderError as error:
        raise HTTPException(502, str(error)) from None


class Reconcile(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{5,100}$")


@router.post("/jobs/{job_id}/reconcile", dependencies=[Depends(operator)])
def reconcile(job_id: str, body: Reconcile, eng: Engine = Depends(get_engine)):
    job = eng.store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["state"] not in ["unknown_effect", "needs_attention"]:
        raise HTTPException(409, "Only uncertain or attention-required jobs may be reconciled")
    session = eng.providers.session(body.session_id)
    if f"cognition-job:{job_id}" not in session.get("tags", []):
        raise HTTPException(409, "Session lacks the matching correlation tag")
    eng.store.update(
        job_id,
        state="running",
        session_id=body.session_id,
        session_url=session["url"],
        started=job.get("started") or session["created_at"],
        error=None,
        next_poll=0,
    )
    eng.store.audit(job_id, "operator_reconciled", {"session_id": body.session_id})
    return eng.store.get(job_id)


@router.post("/jobs/{job_id}/resume-integration", dependencies=[Depends(operator)])
def resume_integration(job_id: str, eng: Engine = Depends(get_engine)):
    job = eng.store.get(job_id)
    if not job or job["kind"] != "integration":
        raise HTTPException(404, "Integration job not found")
    if job["state"] not in ["unknown_effect", "needs_attention", "blocked"]:
        raise HTTPException(409, "Job is not stopped")
    # assemble_candidate reads the branch, merge parents and existing PR before writes.
    eng.store.update(job_id, state="queued", lease_until=0, error=None)
    eng.store.audit(job_id, "operator_requested_integration_readback", {})
    return {"status": "queued_for_github_reconciliation"}


@router.get("/pull-requests")
def pull_requests(
    request: Request,
    kind: str = "",
    bot_only: bool = False,
    search: str = "",
    offset: int = 0,
    eng: Engine = Depends(get_engine),
):
    from .workbench import pull_request_rows

    if kind not in {"", "dependency", "fix", "feature", "revert", "other"} or offset < 0:
        raise HTTPException(422, "Invalid work filter or offset")
    history = request.app.state.analytics
    jobs = eng.store.operational_jobs()
    rows = pull_request_rows(history.pulls(eng.settings.repo), jobs, eng.store.all_publications())
    filtered = [
        row
        for row in rows
        if (not kind or row["category"] == kind)
        and (not bot_only or row["dependabot"])
        and search.lower() in f"{row['number']} {row['title']} {row['author']}".lower()
    ]
    return {
        "repository": eng.settings.repo,
        "branch": eng.settings.branch,
        "enabled": eng.settings.enabled and eng.settings.dependabot_enabled,
        "queue_holds": [
            {
                "id": job["id"],
                "state": job["state"],
                "error": job["error"],
                "pr_number": job["pr_number"],
            }
            for job in jobs
            if job["state"] in {"needs_attention", "unknown_effect"}
        ],
        "sync": history.status(eng.settings.repo),
        "poll": eng.store.recall("dependabot_poll", {}),
        "total": len(filtered),
        "rows": filtered[offset : offset + 50],
        "offset": offset,
        "limit": 50,
    }


@router.get("/learning")
def learning(eng: Engine = Depends(get_engine)):
    return LearningService(eng.settings, eng.store, eng.providers).overview()
