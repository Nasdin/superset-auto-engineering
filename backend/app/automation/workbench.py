"""Cached PR evidence and dispatch explanations; never make provider calls here."""

import re
import time

from ..analytics.metrics import category
from .execution_policy import RESERVED_SESSIONS

LIVE_STATES = {"running", "dispatching", "unknown_effect", "needs_attention"}


def execution_context(settings, jobs, worker, breakers=(), *, now=None):
    now = time.time() if now is None else now
    used = sum(
        j["kind"] != "integration"
        and (j.get("session_id") is not None or j["state"] in {"dispatching", "unknown_effect"})
        for j in jobs
    )
    blockers = []
    if not settings.enabled:
        blockers.append(
            {
                "code": "disabled",
                "message": "New Devin execution is disabled. Existing sessions can still be observed.",
            }
        )
    if not settings.devin_key or not settings.github_token:
        blockers.append(
            {"code": "configuration", "message": "Devin or GitHub credentials are not configured."}
        )
    for job in jobs:
        if job["state"] in LIVE_STATES or (
            job.get("session_id") is not None and job["state"] in {"blocked", "dead_letter"}
        ):
            active = job["state"] in {"running", "dispatching"}
            blockers.append(
                {
                    "code": "active_run" if active else "session_hold",
                    "job_id": job["id"],
                    "pr_number": job.get("pr_number"),
                    "state": job["state"],
                    "session_url": job.get("session_url"),
                    "message": (
                        "The single worker is completing an existing Devin run."
                        if active
                        else job.get("error")
                        or "An existing session needs reconciliation before another can start."
                    ),
                }
            )
    for breaker in breakers:
        if breaker.get("state") == "open":
            blockers.append(
                {
                    "code": "provider_hold",
                    "message": f"{breaker['provider'].title()} execution is held: {breaker.get('reason', 'provider connection requires attention')}.",
                    "retry_at": breaker.get("retry_at"),
                }
            )
    heartbeat = worker.get("at")
    if not heartbeat or now - heartbeat > 180:
        blockers.append(
            {
                "code": "worker_stale",
                "message": "No recent worker heartbeat. Queued work needs an active worker.",
                "observed_at": heartbeat,
            }
        )
    return {
        "enabled": settings.enabled,
        "dependabot_enabled": settings.dependabot_enabled,
        "sessions_used": used,
        "sessions_limit": settings.max_sessions,
        "sessions_remaining": max(0, settings.max_sessions - used),
        "max_acu_per_session": settings.max_acu,
        "worker": worker,
        "blockers": blockers,
    }


def publication_for(pub, row):
    """Job IDs anchor receipt identity; revisions belong after its destination."""
    parts = pub["key"].split(":")
    by_id = {job["id"]: job for job in row["runs"]}
    if parts[0] == "github":
        for index, part in enumerate(parts[1:-1], 1):
            if part in by_id and parts[index + 1] == str(row["number"]):
                return {**pub, "purpose": "report"}
    elif parts[0] == "slack" and len(parts) >= 2 and parts[1] in by_id:
        return {**pub, "purpose": "report"}
    elif parts[0] == "github-ready" and len(parts) >= 3 and parts[1] in by_id:
        if by_id[parts[1]]["pr_number"] == row["number"]:
            return {**pub, "purpose": "readiness"}
    return None


def progress_for(row, execution=None):
    if not row["runs"]:
        return {
            "state": "untracked",
            "label": "No Devin run yet",
            "detail": "No validation evidence has been recorded for this PR.",
            "ready": False,
        }
    job = row["runs"][0]
    state = job["state"]
    result = job.get("result") or {}
    progress = {
        "state": state,
        "label": state.replace("_", " ").capitalize(),
        "detail": job.get("error") or "",
        "job_id": job["id"],
        "session_url": job.get("session_url"),
        "candidate_sha": job.get("candidate_sha"),
        "observed_at": job.get("updated"),
        "validation_pr": job.get("pr_number"),
        "ready": False,
    }
    integrated = job.get("pr_number") != row["number"]
    ci = result.get("ci") or {}
    if state == "review_ready":
        ready = (
            job["kind"] == "validation"
            and ci.get("state") == "success"
            and ci.get("sha") == job.get("candidate_sha")
            and result.get("candidate_sha") == job.get("candidate_sha")
            and result.get("gate") == "review_ready"
            and not result.get("gate_failures")
            and result.get("provenance") == "independent_devin_session"
            and bool(re.fullmatch(r"[a-f0-9]{40}", job.get("candidate_sha") or ""))
        )
        progress.update(
            ready=ready,
            label=("Integrated evidence ready" if integrated else "Evidence ready for review")
            if ready
            else "Readiness needs verification",
            detail=(
                f"Independent evidence and GitHub CI passed for {'integration PR #' + str(job['pr_number']) if integrated else 'this PR'} at the recorded SHA. Confirm the current head and merge requirements on GitHub."
                if ready
                else "A complete independent gate with passing CI has not been recorded for this candidate."
            ),
        )
    elif state == "awaiting_ci":
        progress.update(
            label="Waiting for GitHub checks",
            detail="Runtime evidence is recorded. The release gate stays closed until GitHub checks finish successfully.",
        )
    elif state in {"running", "dispatching"}:
        progress.update(
            label="Devin validating" if job["kind"] == "validation" else "Devin working",
            detail="Follow the active Devin session for execution progress. This candidate is not yet ready for review.",
        )
    elif state in {"prepared", "implemented"}:
        progress.update(
            label="Fix prepared · validation pending",
            detail="Devin prepared the change; fresh independent validation is still required.",
        )
    elif state == "queued":
        progress.update(
            label="Queued for validation" if job["kind"] == "validation" else "Queued for Devin",
            detail="Waiting for the worker to dispatch this recorded job.",
        )
        if execution:
            blockers = execution["blockers"]
            required = RESERVED_SESSIONS.get(job["kind"], 1)
            if (
                job["payload"].get("work_type") == "dependency"
                and not execution["dependabot_enabled"]
            ):
                blockers = [
                    {
                        "code": "dependency_disabled",
                        "message": "Dependabot automation is disabled.",
                    },
                    *blockers,
                ]
            if execution["sessions_remaining"] < required:
                blockers = [
                    {
                        "code": "session_budget",
                        "message": f"This step reserves {required} session slot(s), but only {execution['sessions_remaining']} remain in the configured {execution['sessions_limit']}-session limit. This is not the organization's credit balance.",
                    },
                    *blockers,
                ]
            if blockers:
                blocking = blockers[0]
                progress.update(
                    label="Queued · "
                    + (
                        "another run is active"
                        if blocking["code"] == "active_run"
                        else "waiting for execution"
                    ),
                    detail=blocking["message"],
                    blocker=blocking,
                )
    return progress


def pull_request_rows(pulls, jobs, publications, execution=None):
    indexed = {
        pr["number"]: {
            **pr,
            "category": category(pr),
            "dependabot": pr["author"].lower() == "dependabot[bot]",
            "runs": [],
            "publications": [],
        }
        for pr in pulls
    }
    for job in jobs:
        payload = job["payload"]
        numbers = {job["pr_number"]}
        if job["kind"] == "validation":
            numbers.update(member["pr_number"] for member in payload.get("members", []))
        for number in numbers - {None}:
            row = indexed.setdefault(
                number,
                {
                    "number": number,
                    "title": payload.get("title", f"PR #{number}"),
                    "author": payload.get("author", "Not imported yet"),
                    "category": "dependency"
                    if payload.get("work_type") == "dependency"
                    else "other",
                    "dependabot": payload.get("work_type") == "dependency",
                    "state": "not_imported",
                    "updated_at": None,
                    "runs": [],
                    "publications": [],
                },
            )
            row["runs"].append(job)
    for row in indexed.values():
        row["runs"].sort(key=lambda job: job["created"], reverse=True)
        row["publications"] = [
            matched for pub in publications if (matched := publication_for(pub, row))
        ]
        row["progress"] = progress_for(row, execution)
    return sorted(indexed.values(), key=lambda row: row["number"], reverse=True)
