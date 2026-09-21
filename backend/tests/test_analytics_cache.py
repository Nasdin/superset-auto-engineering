from datetime import date
from unittest.mock import patch

from app.analytics.cache import AnalyticsResultCache
from app.analytics.embedding import Selection, remember_selection
from app.analytics.routes import analysis_slots
from app.analytics.store import AnalyticsStore
from app.automation.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_cache_expiry_mutation_isolation_lru_and_byte_budget():
    now = [0.0]
    cache = AnalyticsResultCache(ttl=10, max_entries=2, max_bytes=100, clock=lambda: now[0])
    value = {"rows": [1]}
    cache.put("a", value)
    value["rows"].append(2)
    returned = cache.get("a")
    returned["rows"].append(3)
    assert cache.get("a") == {"rows": [1]}
    cache.put("b", {"rows": [2]})
    cache.get("a")
    cache.put("c", {"rows": [3]})
    assert cache.get("b") is None
    cache.put("huge", {"rows": ["x" * 101]})
    assert cache.get("huge") is None
    assert cache.get("a")
    now[0] = 10
    assert cache.get("a") is None
    assert cache.get("c") is None
    cache.put("a", {"rows": [4]})
    cache.put("a", {"rows": [5]})
    assert cache.get("a") == {"rows": [5]}


def test_api_cache_hit_avoids_history_reads_and_remains_available_during_busy_miss(tmp_path):
    app = create_app(
        Settings(database=str(tmp_path / "live.db")), demo_database=tmp_path / "demo.db"
    )
    with TestClient(app) as client:
        store = app.state.analytics
        # A durable queue may advance revision on first request; warm its stable
        # revision before checking cache behavior independently of backfill.
        query = "/api/analytics/pull-requests?end=2026-09-19"
        assert client.get(query).status_code == 200
        first = client.get(query).json()
        with patch.object(store, "pulls", side_effect=AssertionError("Cache must avoid full read")):
            assert analysis_slots.acquire(blocking=False)
            try:
                cached = client.get(query)
                assert cached.json() == first
                assert cached.headers["X-Analytics-Cache"] == "hit"
                assert client.get(query + "&kind=fix").status_code == 503
            finally:
                analysis_slots.release()


def test_api_cache_keys_cover_filters_repositories_revision_and_workflow_provenance(tmp_path):
    app = create_app(
        Settings(database=str(tmp_path / "live.db")), demo_database=tmp_path / "demo.db"
    )
    with TestClient(app) as client:
        store = app.state.analytics
        query = "/api/analytics/pull-requests?end=2026-09-19"
        with patch.object(store, "pulls", wraps=store.pulls) as pulls:
            assert client.get(query).status_code == 200
            assert client.get(query).status_code == 200
            for suffix in (
                "&kind=fix",
                "&author=alice",
                "&label=bug",
                "&base=main",
                "&offset=50",
                "&days=60",
                "&comparison=previous",
                "&provenance=tracked",
            ):
                before = pulls.call_count
                response = client.get(query + suffix)
                assert response.status_code == 200
                assert response.headers["X-Analytics-Cache"] == "miss"
                assert before < pulls.call_count <= before + 2
                after = pulls.call_count
                assert client.get(query + suffix).headers["X-Analytics-Cache"] == "hit"
                assert pulls.call_count == after
            before = pulls.call_count
            store.set_status(
                "apache/superset", {"state": "error", "message": "Provider unavailable"}
            )
            assert client.get(query).status_code == 200
            assert pulls.call_count == before + 1
            fork_query = query + "&repository=" + app.state.engine.settings.repo
            assert client.get(fork_query).status_code == 200
            assert client.get(fork_query).status_code == 200
            before = pulls.call_count
            job = app.state.engine.store.enqueue("cache-provenance", "repair", {})
            app.state.engine.store.update(job["id"], pr_number=99)
            assert client.get(fork_query).status_code == 200
            assert pulls.call_count == before + 1


def test_selection_identity_is_stable_per_revision_and_isolates_repository_filters(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    values = Selection(end=date(2026, 9, 19)).resolved("Nasdin/superset")
    identity = remember_selection(store, values)
    assert remember_selection(store, values) == identity
    assert remember_selection(store, {**values, "repository": "Nasdin/superset"}) != identity
    assert remember_selection(store, {**values, "author": "alice"}) != identity
    store.set_status("apache/superset", {"state": "ready"})
    assert remember_selection(store, values) != identity
    store.database.close()


def test_ingestion_between_history_read_and_queue_does_not_cache_old_rows_under_new_revision(
    tmp_path,
):
    app = create_app(
        Settings(database=str(tmp_path / "live.db")), demo_database=tmp_path / "demo.db"
    )
    with TestClient(app) as client:
        store = app.state.analytics
        read = store.pulls
        changed = False

        def read_then_ingest(repository):
            nonlocal changed
            rows = read(repository)
            if not changed:
                changed = True
                store.upsert(
                    repository,
                    [
                        {
                            "number": 7,
                            "title": "fix: concurrently imported",
                            "html_url": "https://github.com/apache/superset/pull/7",
                            "user": {"login": "engineer"},
                            "labels": [],
                            "base": {"ref": "master"},
                            "state": "closed",
                            "created_at": "2026-09-01T00:00:00Z",
                            "updated_at": "2026-09-02T00:00:00Z",
                            "merged_at": "2026-09-02T00:00:00Z",
                            "closed_at": "2026-09-02T00:00:00Z",
                        }
                    ],
                )
            return rows

        query = "/api/analytics/pull-requests?end=2026-09-19"
        with patch.object(store, "pulls", side_effect=read_then_ingest):
            assert client.get(query).status_code == 200
        second = client.get(query)
        assert second.status_code == 200
        assert second.json()["current"]["merged"] == 1
        assert second.json()["rows"][0]["number"] == 7
