from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .metrics import analyze, months_before

router = APIRouter(prefix="/api/analytics", tags=["repository analytics"])


@router.get("/pull-requests")
def pull_requests(
    request: Request,
    repository: str = "apache/superset",
    end: date | None = None,
    days: int = Query(default=30, ge=7, le=180),
    comparison: Literal["six_months", "previous", "custom"] = "six_months",
    baseline_end: date | None = None,
    author: str = Query(default="", max_length=100),
    label: str = Query(default="", max_length=200),
    base: str = Query(default="", max_length=200),
    kind: Literal["", "fix", "dependency", "feature", "revert", "other", "bot"] = "",
    provenance: Literal["all", "tracked", "untracked"] = "all",
    offset: int = Query(default=0, ge=0, le=100000),
):
    engine = request.app.state.engine
    repositories = list(dict.fromkeys(["apache/superset", engine.settings.repo]))
    if repository not in repositories:
        raise HTTPException(422, "Repository is not in the configured analytics scope")
    end = end or (datetime.now(UTC).date() - timedelta(days=1))
    if not date(2010, 1, 1) <= end < datetime.now(UTC).date():
        raise HTTPException(422, "Choose a completed UTC day from 2010 onward")
    baseline_end = (
        baseline_end
        if comparison == "custom"
        else (end - timedelta(days=days) if comparison == "previous" else months_before(end))
    )
    if baseline_end is None or not date(2009, 1, 1) <= baseline_end < end:
        raise HTTPException(422, "Baseline end must precede the current end date")
    tracked = (
        {
            job["pr_number"]
            for job in engine.store.operational_jobs()
            if job["kind"] in {"repair", "patch", "dependency"} and job.get("pr_number")
        }
        if repository == engine.settings.repo
        else set()
    )
    completed = {
        job["pr_number"]
        for job in engine.store.operational_jobs()
        if job["pr_number"] in tracked
        and job.get("session_id")
        and job["state"] in {"implemented", "prepared"}
    }
    store = request.app.state.analytics
    return {
        "repository": repository,
        "repositories": repositories,
        "workflow_repository": engine.settings.repo,
        "provenance": "GitHub REST API / persisted public PR metadata",
        **analyze(
            store.pulls(repository),
            store.status(repository),
            end=end,
            days=days,
            baseline_end=baseline_end,
            author=author,
            label=label,
            base=base,
            kind=kind,
            tracked=tracked,
            completed=completed,
            provenance=provenance,
            offset=offset,
        ),
    }
