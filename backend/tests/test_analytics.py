from datetime import UTC, date, datetime, timedelta

import httpx
from app.analytics.metrics import analyze, category, months_before
from app.analytics.store import AnalyticsStore
from app.analytics.sync import sync_repository
from app.automation.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def record(number=1, *, created="2026-09-01T00:00:00Z", merged="2026-09-10T00:00:00Z", **extra):
    return {
        "number": number,
        "title": "fix: query regression",
        "url": f"https://github.com/apache/superset/pull/{number}",
        "author": "engineer",
        "labels": ["bug"],
        "base": "master",
        "state": "closed",
        "created_at": created,
        "updated_at": merged or created,
        "closed_at": merged,
        "merged_at": merged,
        **extra,
    }


def provider_record(number=1, **kwargs):
    pr = record(number, **kwargs)
    return {
        **pr,
        "html_url": pr["url"],
        "base": {"ref": pr["base"]},
        "user": {"login": pr["author"]},
        "labels": [{"name": label} for label in pr["labels"]],
    }


def report(pulls, **kwargs):
    return analyze(
        pulls,
        {"complete": True, "coverage_from": "2025-01-01", "last_success": "2026-09-20T00:00:00Z"},
        end=date(2026, 9, 19),
        days=30,
        baseline_end=date(2026, 3, 19),
        **kwargs,
    )


def test_calendar_months_and_merge_boundaries():
    assert months_before(date(2024, 8, 31)) == date(2024, 2, 29)
    assert months_before(date(2025, 8, 31)) == date(2025, 2, 28)
    result = report(
        [
            record(1, created="2026-08-01T00:00:00Z", merged="2026-08-21T00:00:00Z"),
            record(2, merged="2026-09-19T23:59:59Z"),
            record(3, merged="2026-09-20T00:00:00Z"),
            record(4, merged=None, closed_at="2026-09-10T00:00:00Z"),
            record(5, created="2026-08-01T00:00:00Z", merged="2026-08-21T00:30:00+01:00"),
        ]
    )
    assert result["current"]["merged"] == 2
    assert result["closed_unmerged"] == 1
    assert {pr["number"] for pr in result["rows"]} == {1, 2}
    assert result["baseline"]["median_hours"] is None
    assert result["change_percent"] is None


def test_filter_comparison_chart_and_drilldown_consistency():
    pulls = [
        record(i, created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z")
        for i in range(1, 6)
    ]
    pulls += [
        record(i, created="2026-03-01T00:00:00Z", merged="2026-03-03T00:00:00Z")
        for i in range(6, 11)
    ]
    pulls += [record(11, author="someone-else", labels=["dependencies"])]
    result = report(
        pulls,
        author="engineer",
        label="bug",
        base="master",
        kind="fix",
        provenance="tracked",
        tracked=set(range(1, 11)),
    )
    assert result["change_percent"] == -50
    assert result["current"]["sample_size"] == 5
    assert result["baseline"]["p75_hours"] == 48
    assert result["trend"][-1] == result["current"]
    assert result["total_rows"] == 5
    assert all(pr["tracked"] for pr in result["rows"])
    assert report(pulls, provenance="tracked")["current"]["merged"] == 0
    assert report(pulls, provenance="untracked", tracked=set(range(1, 12)))["rows"] == []


def test_invalid_dates_coverage_and_zero_baseline():
    pulls = [record(1, created="2026-09-12T00:00:00Z"), record(2, merged=None, state="open")]
    result = report(pulls)
    assert result["current"]["excluded_invalid"] == 1
    assert result["current"]["median_hours"] is None
    assert result["observed_open"] == 1
    args = dict(end=date(2026, 9, 19), days=30, baseline_end=date(2026, 3, 19))
    rows = [record(i) for i in range(5)] + [
        record(i + 5, created="2026-03-01T00:00:00Z", merged="2026-03-01T00:00:00Z")
        for i in range(5)
    ]
    assert report(rows)["change_percent"] is None
    result = analyze(rows, {"complete": False}, **args)
    assert not result["current"]["covered"]
    assert result["change_percent"] is None
    assert category(record(title="Revert fix: bump dependency")) == "revert"
    assert category(record(title="chore: bump library")) == "dependency"
    assert category(record(title="docs: examples", labels=[])) == "docs"


def test_pagination_upsert_and_cutoff(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    calls = []

    def handler(request):
        page = int(request.url.params["page"])
        calls.append(page)
        return httpx.Response(
            200,
            json=[provider_record(i) for i in range(100)]
            if page == 1
            else [
                provider_record(101, created="2020-01-01T00:00:00Z", merged="2020-01-02T00:00:00Z")
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sync_repository(store, "apache/superset", client, now=datetime(2026, 9, 20, tzinfo=UTC))
        sync_repository(store, "apache/superset", client, now=datetime(2026, 9, 21, tzinfo=UTC))
    assert calls == [1, 2, 1]
    assert len(store.pulls("apache/superset")) == 101
    assert store.status("apache/superset")["complete"]
    assert store.status("apache/superset")["coverage_from"] == "2024-09-21"
    assert store.pulls("other/repo") == []


def test_failed_sync_retains_watermark_and_partial_first_import(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    initial = {
        "state": "ready",
        "complete": True,
        "coverage_from": "2024-10-01",
        "last_success": "2026-09-18T00:00:00+00:00",
    }
    store.set_status("apache/superset", initial)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        sync_repository(store, "apache/superset", client)
    assert store.status("apache/superset")["last_success"] == initial["last_success"]
    assert store.status("apache/superset")["state"] == "error"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[provider_record(i) for i in range(100)])
        )
    ) as client:
        sync_repository(
            store, "new/repo", client, now=datetime(2026, 9, 20, tzinfo=UTC), max_pages=1
        )
    assert store.status("new/repo")["state"] == "partial"
    assert not store.status("new/repo").get("complete")


def test_api_scope_dates_provenance_and_pagination(tmp_path):
    app = create_app(
        Settings(database=str(tmp_path / "live.db")), demo_database=tmp_path / "demo.db"
    )
    with TestClient(app) as client:
        app.state.analytics.upsert("apache/superset", [provider_record(i) for i in range(60)])
        repair = app.state.engine.store.enqueue("repair-test", "repair", {})
        app.state.engine.store.update(repair["id"], pr_number=1)
        result = client.get("/api/analytics/pull-requests?end=2026-09-19&offset=50").json()
        assert result["total_rows"] == 60
        assert len(result["rows"]) == 10
        assert not any(row["tracked"] for row in result["rows"])
        for query in [
            "repository=other/repo",
            "days=0",
            "comparison=custom",
            "baseline_end=2027-01-01&comparison=custom",
            "end=2030-01-01",
        ]:
            assert client.get("/api/analytics/pull-requests?" + query).status_code == 422
        result = client.get(
            "/api/analytics/pull-requests?end=2026-09-19&comparison=previous"
        ).json()
        assert result["baseline"]["end"] == "2026-08-20"
        assert (
            client.get("/api/analytics/pull-requests").json()["current"]["end"]
            == (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        )


def test_coverage_requires_a_full_day_and_offline_gaps_reset_it(tmp_path):
    from app.analytics.metrics import covered

    summary = {"start": "2026-09-01", "end": "2026-09-19"}
    status = {
        "complete": True,
        "coverage_from": "2024-01-01",
        "last_success": "2026-09-19T23:59:59Z",
    }
    assert not covered(status, summary)
    status["last_success"] = "2026-09-20T00:00:00Z"
    assert covered(status, summary)
    store = AnalyticsStore(tmp_path / "analytics.db")
    store.set_status("apache/superset", {**status, "last_success": "2020-01-01T00:00:00+00:00"})
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    ) as client:
        sync_repository(store, "apache/superset", client, now=datetime(2026, 9, 20, tzinfo=UTC))
    assert store.status("apache/superset")["coverage_from"] == "2024-09-21"


def test_public_snapshot_bootstraps_once_and_never_overwrites_live_history(tmp_path):
    seed_path = tmp_path / "public.sqlite3"
    seed = AnalyticsStore(seed_path)
    seed.upsert("apache/superset", [provider_record()])
    seed.set_status("apache/superset", {"state": "ready"})
    db_path = tmp_path / "local.db"
    local = AnalyticsStore(db_path, seed=seed_path)
    assert len(local.pulls("apache/superset")) == 1
    local.upsert("apache/superset", [provider_record(title="updated title")])
    AnalyticsStore(db_path, seed=seed_path)
    assert local.pulls("apache/superset")[0]["title"] == "updated title"
    assert seed.pulls("apache/superset")[0]["title"] == "fix: query regression"


def test_superset_native_label_signals():
    assert category(record(title="Repair query behavior", labels=["#bug"])) == "fix"
    assert (
        category(record(title="Refresh connector", labels=["dependencies:python"])) == "dependency"
    )
    assert category(record(title="Library compatibility", labels=[".dependency"])) == "dependency"


def test_analytics_switch_is_read_only_and_keeps_workflows_on_fork(tmp_path):
    app = create_app(
        Settings(database=str(tmp_path / "live.db")), demo_database=tmp_path / "demo.db"
    )
    with TestClient(app) as client:
        app.state.analytics.upsert("apache/superset", [provider_record(10), provider_record(11)])
        app.state.analytics.upsert("Nasdin/superset", [provider_record(1)])
        for repository, expected in [("apache/superset", 2), ("Nasdin/superset", 1)]:
            response = client.get(
                "/api/analytics/pull-requests",
                params={"repository": repository, "end": "2026-09-19"},
            ).json()
            assert response["repository"] == repository
            assert response["workflow_repository"] == "Nasdin/superset"
            assert response["current"]["merged"] == expected
            overview = client.get("/api/live/overview").json()
            assert overview["repository"] == "Nasdin/superset"
            assert overview["jobs"] == []
