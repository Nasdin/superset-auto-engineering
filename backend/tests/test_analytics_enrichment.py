from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.analytics.enrichment import enrich_repository
from app.analytics.store import DETAIL_FIELDS, AnalyticsStore

NOW = datetime(2026, 9, 21, tzinfo=UTC)
REPOSITORY = "apache/superset"


def provider(number=1, **changes):
    return {
        "number": number,
        "title": "fix: regression",
        "html_url": "https://github.com/test",
        "user": {"login": "engineer", "type": "User"},
        "labels": [],
        "base": {"ref": "master"},
        "state": "closed",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "closed_at": "2026-09-20T00:00:00Z",
        "merged_at": "2026-09-20T00:00:00Z",
        **changes,
    }


def detail(pr, **changes):
    return {**pr, "commits": 3, "additions": 100, "deletions": 40, "changed_files": 2, **changes}


def review(at="2026-09-10T00:00:00Z", *, login="reviewer", kind="User"):
    return {"user": {"login": login, "type": kind}, "state": "APPROVED", "submitted_at": at}


def commit(number, at):
    return {"sha": f"commit-{number}", "commit": {"committer": {"date": at}}}


def run(tmp_path, handler, *, prs=None, **kwargs):
    store = AnalyticsStore(tmp_path / "analytics.db")
    store.upsert(REPOSITORY, prs or [provider()])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        progress = enrich_repository(store, REPOSITORY, client, now=NOW, **kwargs)
    return store, progress


def test_human_review_and_strict_commit_cutoffs_with_pagination(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.url.path, request.url.params.get("page")))
        if request.url.path.endswith("/reviews"):
            if request.url.params["page"] == "1":
                return httpx.Response(
                    200,
                    json=[review(login="engineer"), review(kind="Bot")],
                    headers={"Link": '<https://api.github.com/next?page=2>; rel="next"'},
                )
            return httpx.Response(200, json=[review()])
        if request.url.path.endswith("/commits"):
            if request.url.params["page"] == "1":
                return httpx.Response(
                    200,
                    json=[commit(1, "2026-09-10T00:00:00Z")],
                    headers={"Link": '<https://api.github.com/next?page=2>; rel="next"'},
                )
            return httpx.Response(
                200, json=[commit(2, "2026-09-20T00:00:00Z"), commit(3, "2026-09-20T00:00:01Z")]
            )
        return httpx.Response(200, json=detail(provider()))

    store, progress = run(tmp_path, handler)
    row = store.pulls(REPOSITORY)[0]
    assert row["rework_commits"] == 1
    assert row["first_review_at"] == "2026-09-10T00:00:00+00:00"
    assert row["commits_count"] == 3
    assert row["author_type"] == "User"
    assert row["enrichment_state"] == "complete"
    assert progress["complete"] == 1
    assert progress["requests"] == 5
    assert [page for path, page in calls if path.endswith("/reviews")] == ["1", "2"]


@pytest.mark.parametrize("failure", ["truncated", "http", "invalid"])
def test_incomplete_review_scan_retains_detail_but_never_zero(tmp_path, failure):
    def handler(request):
        if request.url.path.endswith("/reviews"):
            if failure == "http":
                return httpx.Response(500)
            if failure == "invalid":
                return httpx.Response(200, json={"message": "invalid"})
            return httpx.Response(
                200,
                json=[review(login="engineer")],
                headers={"Link": '<https://api.github.com/next>; rel="next"'},
            )
        return httpx.Response(200, json=detail(provider()))

    store, progress = run(tmp_path, handler, max_pages=1)
    row = store.pulls(REPOSITORY)[0]
    assert row["commits_count"] == 3
    assert row["additions"] == 100
    assert row["rework_commits"] is None
    assert row["enrichment_state"] == "partial"
    assert progress["partial"] == 1


def test_no_human_review_zero_only_after_complete_scan_and_pending_ignored(tmp_path):
    def handler(request):
        if request.url.path.endswith("/reviews"):
            return httpx.Response(
                200, json=[review(login="engineer"), review(kind="Bot"), {"state": "PENDING"}]
            )
        assert not request.url.path.endswith("/commits")
        return httpx.Response(200, json=detail(provider()))

    store, _ = run(tmp_path, handler)
    assert store.pulls(REPOSITORY)[0]["rework_commits"] == 0
    assert store.pulls(REPOSITORY)[0]["enrichment_state"] == "complete"


@pytest.mark.parametrize("reviews", [[{"state": "APPROVED"}], [review(at=None)]])
def test_unknown_review_fields_do_not_establish_zero(tmp_path, reviews):
    store, _ = run(
        tmp_path,
        lambda request: httpx.Response(
            200, json=reviews if request.url.path.endswith("/reviews") else detail(provider())
        ),
    )
    assert store.pulls(REPOSITORY)[0]["rework_commits"] is None


def test_missing_or_invalid_detail_counts_are_unknown_not_zero(tmp_path):
    store, _ = run(
        tmp_path,
        lambda request: httpx.Response(
            200,
            json=[]
            if request.url.path.endswith("/reviews")
            else detail(provider(), commits=None, additions=True, deletions=-1),
        ),
    )
    row = store.pulls(REPOSITORY)[0]
    assert row["commits_count"] is None
    assert row["additions"] is None
    assert row["deletions"] is None
    assert row["changed_files"] == 2
    assert row["rework_commits"] == 0
    assert row["enrichment_state"] == "partial"


@pytest.mark.parametrize(
    "total,commits",
    [(251, []), (3, [commit(1, "2026-09-11T00:00:00Z")]), (1, [{"sha": "a", "commit": {}}])],
)
def test_incomplete_commit_history_never_zero(tmp_path, total, commits):
    def handler(request):
        if request.url.path.endswith("/reviews"):
            return httpx.Response(200, json=[review()])
        if request.url.path.endswith("/commits"):
            assert total <= 250
            return httpx.Response(200, json=commits)
        return httpx.Response(200, json=detail(provider(), commits=total))

    store, _ = run(tmp_path, handler)
    row = store.pulls(REPOSITORY)[0]
    assert row["rework_commits"] is None
    assert row["commits_count"] == total
    assert row["first_review_at"] is not None


@pytest.mark.parametrize("merged", [None, "2026-09-20T00:00:00Z"])
def test_refresh_preserves_then_invalidates_measurements(tmp_path, merged):
    pr = provider(merged_at=merged, state="closed" if merged else "open")
    store, _ = run(
        tmp_path,
        lambda request: httpx.Response(
            200, json=[] if request.url.path.endswith("/reviews") else detail(pr)
        ),
        prs=[pr],
    )
    store.upsert(REPOSITORY, [pr])
    assert store.pulls(REPOSITORY)[0]["commits_count"] == 3
    store.upsert(REPOSITORY, [{**pr, "updated_at": "2026-09-21T00:00:00Z"}])
    row = store.pulls(REPOSITORY)[0]
    assert row["commits_count"] is None
    assert row["rework_commits"] is None
    assert row["details_updated_at"] is None
    assert row["enrichment_state"] == "stale"
    assert not store.enrich(
        REPOSITORY, 1, {"commits_count": 42}, expected_updated_at=pr["updated_at"]
    )


def test_budget_resume_and_month_category_fairness(tmp_path):
    prs = [
        provider(
            i,
            title="feat: thing" if i % 2 else "fix: thing",
            merged_at=f"2026-0{month}-20T00:00:00Z",
        )
        for month, start in [(9, 1), (8, 11), (3, 21)]
        for i in range(start, start + 4)
    ]
    by_number = {pr["number"]: pr for pr in prs}
    seen = []

    def handler(request):
        if request.url.path.endswith("/reviews"):
            return httpx.Response(200, json=[])
        number = int(request.url.path.rsplit("/", 1)[-1])
        seen.append(number)
        return httpx.Response(200, json=detail(by_number[number]))

    store, progress = run(tmp_path, handler, prs=prs, max_prs=6)
    assert progress["complete"] == 6
    assert progress["remaining"] == 6
    assert {by_number[n]["merged_at"][:7] for n in seen} == {"2026-09", "2026-08", "2026-03"}
    first_seen = set(seen)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        progress = enrich_repository(store, REPOSITORY, client, now=NOW, max_prs=6)
    assert progress["complete"] == 12
    assert not first_seen.intersection(seen[6:])
    assert store.status(REPOSITORY)["enrichment"] == progress


def test_rate_limit_stops_and_keeps_successful_detail(tmp_path):
    store, progress = run(
        tmp_path,
        lambda _: httpx.Response(
            200, json=detail(provider()), headers={"x-ratelimit-remaining": "100"}
        ),
        prs=[provider(), provider(2)],
    )
    assert progress["requests"] == 1
    assert progress["rate_limited"]
    row = next(pr for pr in store.pulls(REPOSITORY) if pr["number"] == 1)
    assert row["commits_count"] == 3
    assert row["rework_commits"] is None


def test_request_budget_and_error_cooldown_allow_other_prs(tmp_path):
    store, progress = run(
        tmp_path, lambda _: httpx.Response(500), prs=[provider(), provider(2)], max_requests=1
    )
    assert progress["requests"] == 1
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=[] if request.url.path.endswith("/reviews") else detail(provider(2))
            )
        )
    ) as client:
        progress = enrich_repository(store, REPOSITORY, client, now=NOW + timedelta(hours=1))
    assert progress["processed"] == 1
    assert progress["complete"] == 1


def test_provider_detail_version_mismatch_cannot_publish_metrics(tmp_path):
    store, _ = run(
        tmp_path,
        lambda _: httpx.Response(200, json=detail(provider(), updated_at="2026-09-21T00:00:00Z")),
    )
    row = store.pulls(REPOSITORY)[0]
    assert row.get("commits_count") is None
    assert row["enrichment_state"] == "stale"


@pytest.mark.parametrize("changed", [True, False])
def test_retry_invalidates_known_changed_snapshot_but_preserves_on_network_error(tmp_path, changed):
    def initial(request):
        if request.url.path.endswith("/reviews"):
            return httpx.Response(200, json=[review()])
        if request.url.path.endswith("/commits"):
            return httpx.Response(503)
        return httpx.Response(200, json=detail(provider()))

    store, _ = run(tmp_path, initial)
    previous = store.pulls(REPOSITORY)[0]
    assert previous["enrichment_state"] == "partial"
    assert previous["commits_count"] == 3
    assert previous["first_review_at"] is not None

    def retry(request):
        assert not request.url.path.endswith(("/reviews", "/commits"))
        if changed:
            return httpx.Response(
                200, json=detail(provider(), commits=9, updated_at="2026-09-21T00:00:00Z")
            )
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(retry)) as client:
        enrich_repository(store, REPOSITORY, client, now=NOW + timedelta(days=1))
    row = store.pulls(REPOSITORY)[0]
    if changed:
        assert row["enrichment_state"] == "stale"
        assert all(row[key] is None for key in DETAIL_FIELDS)
    else:
        assert row["enrichment_state"] == "error"
        for key in DETAIL_FIELDS:
            if key != "details_updated_at":
                assert row[key] == previous[key]
