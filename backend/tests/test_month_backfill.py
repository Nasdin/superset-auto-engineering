import json
from datetime import date

import httpx
import pytest
from app.analytics.backfill import MonthBackfill
from app.analytics.metrics import covered
from app.analytics.store import AnalyticsStore

REPO = "apache/superset"


@pytest.fixture
def history(tmp_path):
    store = AnalyticsStore(tmp_path / "history.db")
    yield store
    store.database.close()


def queued(store, *, start="2026-03-01", end="2026-03-31"):
    with store.connect() as db:
        db.execute(
            "INSERT INTO analytics_months(repository,month,requested_through,state,progress,updated) "
            "VALUES(:repo,:month,:end,'queued',:progress,0)",
            {
                "repo": REPO,
                "month": start[:7] + "-01",
                "end": end,
                "progress": json.dumps({"ranges": [[start, end]], "page": 1, "pending": []}),
            },
        )


def saved(store):
    with store.connect() as db:
        return dict(db.execute("SELECT * FROM analytics_months LIMIT 1").fetchone())


def result(numbers=(), *, total=None, incomplete=False):
    return httpx.Response(
        200,
        json={
            "total_count": len(numbers) if total is None else total,
            "incomplete_results": incomplete,
            "items": [{"number": number} for number in numbers],
        },
    )


def canonical(number=1):
    return {
        "number": number,
        "title": "fix: canonical PR metadata",
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "user": {"login": "engineer", "type": "User"},
        "labels": [{"name": "bug"}],
        "base": {"ref": "master"},
        "state": "closed",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2026-03-04T00:00:00Z",
        "merged_at": "2026-03-03T00:00:00Z",
        "closed_at": "2026-03-03T00:00:00Z",
    }


def test_requests_deduplicate_empty_months_and_skip_only_verified_coverage(history):
    service = MonthBackfill(history, clock=lambda: 1000)
    filters = dict(end=date(2026, 9, 19), days=30, baseline_end=date(2026, 3, 19))
    first = service.request_selection(REPO, **filters)
    assert first["state"] == "loading"
    assert first["pending_months"] > 6
    revision = history.revision(REPO)
    assert service.request_selection(REPO, **filters) == first
    assert history.revision(REPO) == revision
    history.set_status(
        "Nasdin/superset",
        {"complete": True, "coverage_from": "2024-01-01", "last_success": "2026-09-20T00:00:00Z"},
    )
    # An entirely absent month gets a cheap check even under broad sync coverage.
    assert service.request_selection("Nasdin/superset", **filters)["state"] == "loading"
    with history.connect() as db:
        db.execute(
            "UPDATE analytics_months SET state='ready',covered_through=requested_through "
            "WHERE repository=:repo",
            {"repo": REPO},
        )
    assert service.request_selection(REPO, **filters)["state"] == "ready"
    assert history.pulls(REPO) == []  # Absence alone never proved a zero month.


def test_missing_month_with_broad_coverage_is_fetched_once_and_empty_receipt_reused(history):
    history.set_status(
        REPO,
        {"complete": True, "coverage_from": "2024-01-01", "last_success": "2026-09-20T00:00:00Z"},
    )
    service = MonthBackfill(history, clock=lambda: 1000)
    filters = dict(end=date(2026, 9, 19), days=30, baseline_end=date(2026, 3, 19))
    loading = service.request_selection(REPO, **filters)
    calls = []

    def provider(request):
        calls.append(request.url.path)
        return result()

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        for _ in range(loading["pending_months"]):
            assert service.run_once(client)
        assert not service.run_once(client)
        assert service.request_selection(REPO, **filters)["state"] == "ready"
        assert not service.run_once(client)
    assert len(calls) == loading["pending_months"]


def test_canonical_metadata_hydration_resumes_after_process_restart(history):
    queued(history)
    paths = []

    def provider(request):
        paths.append(request.url.path)
        return (
            result([1])
            if request.url.path == "/search/issues"
            else httpx.Response(200, json=canonical())
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert MonthBackfill(history, clock=lambda: 1000).run_once(client, max_requests=1)
        assert json.loads(saved(history)["progress"])["pending"] == [1]
        reopened = AnalyticsStore(history.path)
        try:
            assert MonthBackfill(reopened, clock=lambda: 1000).run_once(client, max_requests=2)
        finally:
            reopened.database.close()
    assert paths == ["/search/issues", "/repos/apache/superset/pulls/1"]
    assert saved(history)["state"] == "ready"
    assert history.pulls(REPO)[0]["base"] == "master"
    assert history.pulls(REPO)[0]["created_at"].startswith("2020")
    assert covered(history.status(REPO), {"start": "2026-03-01", "end": "2026-03-31"})


def test_empty_month_is_covered_only_after_complete_github_search(history):
    queued(history)
    assert not covered(history.status(REPO), {"start": "2026-03-01", "end": "2026-03-31"})
    with httpx.Client(transport=httpx.MockTransport(lambda _: result())) as client:
        assert MonthBackfill(history, clock=lambda: 1000).run_once(client)
    assert saved(history)["state"] == "ready"
    assert covered(history.status(REPO), {"start": "2026-03-01", "end": "2026-03-31"})
    assert history.pulls(REPO) == []


@pytest.mark.parametrize(
    "reply", [result(incomplete=True), result(total=5), result([1], total=101)]
)
def test_incomplete_pages_never_mark_month_ready(history, reply):
    queued(history)
    with httpx.Client(transport=httpx.MockTransport(lambda _: reply)) as client:
        MonthBackfill(history, clock=lambda: 1000).run_once(client)
    assert saved(history)["state"] == "retry"
    assert saved(history)["covered_through"] is None


def test_rate_limit_retry_after_and_bounded_dead_letter(history):
    queued(history)
    now = [1000.0]
    service = MonthBackfill(history, clock=lambda: now[0])
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert service.run_once(client)
        assert saved(history)["next_retry"] == 1120
        assert not service.run_once(client)
        for _ in range(7):
            now[0] = saved(history)["next_retry"]
            assert service.run_once(client)
        assert saved(history)["state"] == "dead_letter"
        now[0] += 86400
        assert not service.run_once(client)
    assert len(calls) == 8
    assert saved(history)["covered_through"] is None


def test_auth_failure_is_blocked_without_hot_retry(history):
    queued(history)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
        service = MonthBackfill(history, clock=lambda: 1000)
        assert service.run_once(client)
        assert not service.run_once(client)
    assert saved(history)["state"] == "blocked"


def test_search_ceiling_splits_ranges_and_daily_overflow_is_visible(history):
    queued(history)
    queries = []

    def provider(request):
        queries.append(request.url.params["q"])
        return result(total=1001) if len(queries) == 1 else result()

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        MonthBackfill(history, clock=lambda: 1000).run_once(client)
    assert queries == [
        "repo:apache/superset is:pr is:merged merged:2026-03-01..2026-03-31",
        "repo:apache/superset is:pr is:merged merged:2026-03-01..2026-03-16",
        "repo:apache/superset is:pr is:merged merged:2026-03-17..2026-03-31",
    ]
    assert saved(history)["state"] == "ready"
    with history.connect() as db:
        db.execute("DELETE FROM analytics_months")
    queued(history, start="2026-03-01", end="2026-03-01")
    with httpx.Client(transport=httpx.MockTransport(lambda _: result(total=1001))) as client:
        MonthBackfill(history, clock=lambda: 1000).run_once(client)
    assert saved(history)["state"] == "blocked"
    assert saved(history)["covered_through"] is None


def test_expired_claim_cannot_commit_cursor_after_replacement(history):
    queued(history)
    now = [1000.0]
    first = MonthBackfill(history, clock=lambda: now[0])
    stale = first._claim()
    assert MonthBackfill(history, clock=lambda: now[0])._claim() is None
    now[0] += 181
    replacement = MonthBackfill(history, clock=lambda: now[0])._claim()
    assert replacement["lease_token"] != stale["lease_token"]
    assert not first._save(stale, {"ranges": [], "page": 1, "pending": []}, state="ready")
    assert saved(history)["covered_through"] is None
    assert saved(history)["lease_token"] == replacement["lease_token"]


def test_expired_worker_cannot_overwrite_pr_after_canonical_http_returns(history):
    queued(history)
    now = [1000.0]
    service = MonthBackfill(history, clock=lambda: now[0])

    def provider(request):
        if request.url.path == "/search/issues":
            return result([1])
        now[0] += 181
        replacement = MonthBackfill(history, clock=lambda: now[0])._claim()
        assert replacement is not None
        return httpx.Response(200, json=canonical())

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert not service.run_once(client)
    assert history.pulls(REPO) == []
    assert saved(history)["covered_through"] is None


def test_canonical_merge_outside_requested_month_is_not_published(history):
    queued(history)

    def provider(request):
        if request.url.path == "/search/issues":
            return result([1])
        return httpx.Response(200, json={**canonical(), "merged_at": "2026-04-01T00:00:00Z"})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        MonthBackfill(history, clock=lambda: 1000).run_once(client)
    assert saved(history)["state"] == "retry"
    assert saved(history)["covered_through"] is None
    assert history.pulls(REPO) == []


@pytest.mark.parametrize("resource,remaining", [("core", "100"), ("search", "1")])
def test_rate_limit_reserve_checkpoints_pending_work_and_survives_worker_restart(
    history, resource, remaining
):
    queued(history)
    now = [1000.0]
    calls = []

    def provider(request):
        calls.append(request.url.path)
        if request.url.path == "/search/issues":
            response = result([1])
            response.headers.update(
                {
                    "X-RateLimit-Resource": resource,
                    "X-RateLimit-Remaining": remaining,
                    "X-RateLimit-Reset": "2000",
                }
            )
            return response
        return httpx.Response(200, json=canonical())

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        first = MonthBackfill(history, clock=lambda: now[0])
        assert first.run_once(client)
        assert saved(history)["state"] == "queued"
        assert saved(history)["next_retry"] == 2000
        assert json.loads(saved(history)["progress"])["pending"] == [1]
        assert not first.run_once(client)
        restarted = MonthBackfill(history, clock=lambda: now[0])
        assert not restarted.run_once(client)
        assert calls == ["/search/issues"]
        now[0] = 2000
        assert restarted.run_once(client)
    assert saved(history)["state"] == "ready"
    assert calls == ["/search/issues", "/repos/apache/superset/pulls/1"]
