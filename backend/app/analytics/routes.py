from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .backfill import MonthBackfill
from .metrics import analyze, months_before

router = APIRouter(prefix="/api/analytics", tags=["repository analytics"])
analysis_slots = BoundedSemaphore(1)


@contextmanager
def analysis_capacity():
    """Bound full-history Python allocations, not just database connections.

    Per process, deliberately fail fast so overload cannot fill the threadpool
    with waiting analyses. Replace with SQL read models before raising capacity.
    """
    if not analysis_slots.acquire(blocking=False):
        raise HTTPException(
            503,
            "Analytics is busy. Please retry shortly.",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        analysis_slots.release()


@router.get("/pull-requests")
def pull_requests(
    request: Request,
    response: Response,
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
    jobs = engine.store.operational_jobs() if repository == engine.settings.repo else []
    tracked = (
        {
            job["pr_number"]
            for job in jobs
            if job["kind"] in {"repair", "patch", "dependency", "maintenance"}
            and job.get("pr_number")
        }
        if repository == engine.settings.repo
        else set()
    )
    completed = {
        job["pr_number"]
        for job in jobs
        if job["pr_number"] in tracked
        and job.get("session_id")
        and (
            job["state"] in {"implemented", "prepared"}
            or (
                job["kind"] == "maintenance"
                and job["state"] == "completed"
                and job.get("candidate_sha")
            )
        )
    }
    store = request.app.state.analytics
    cache = request.app.state.analytics_cache
    # A cheap revision lookup replaces repeated full-history reads. Workflow
    # provenance is another input and must invalidate independently of ingestion.
    key = (
        repository,
        store.revision(repository),
        end,
        days,
        baseline_end,
        author,
        label,
        base,
        kind,
        provenance,
        offset,
        tuple(sorted(tracked)),
        tuple(sorted(completed)),
    )
    if (result := cache.get(key)) is not None:
        response.headers["X-Analytics-Cache"] = "hit"
        return result
    with analysis_capacity():
        # A concurrent miss may have completed while this request read its key.
        if (result := cache.get(key)) is not None:
            response.headers["X-Analytics-Cache"] = "hit"
            return result
        stored_pulls = store.pulls(repository)
        loading = MonthBackfill(store).request_selection(
            repository, end=end, days=days, baseline_end=baseline_end, stored_pulls=stored_pulls
        )
        latest_revision = store.revision(repository)
        if latest_revision != key[1]:
            # Queue creation or concurrent ingestion changed the snapshot. Capture
            # its revision before rereading, never label old rows with a new key.
            key = (key[0], latest_revision, *key[2:])
            stored_pulls = store.pulls(repository)
        result = {
            "repository": repository,
            "data_revision": key[1],
            "repositories": repositories,
            "workflow_repository": engine.settings.repo,
            "provenance": "GitHub REST API / persisted public PR metadata",
            "backfill": loading,
            **analyze(
                stored_pulls,
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
        cache.put(key, result)
        response.headers["X-Analytics-Cache"] = "miss"
        return result
