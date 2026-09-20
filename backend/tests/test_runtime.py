from dataclasses import replace

import httpx
import pytest
from app.automation.config import Settings
from app.automation.providers import Providers
from app.automation.runtime import create_runtime
from app.main import create_app
from fastapi.testclient import TestClient


def test_settings_read_environment_at_startup(monkeypatch):
    monkeypatch.setenv("DEVIN_MAX_ACU", "3")
    assert Settings.from_env().max_acu == 3
    monkeypatch.setenv("DEVIN_MAX_ACU", "7")
    assert Settings.from_env().max_acu == 7


@pytest.mark.parametrize(
    "changes",
    [
        {"repo": "apache/superset"},
        {"repo": "owner/repo/issues"},
        {"poll_seconds": 0},
        {"max_acu": -1},
    ],
)
def test_invalid_configuration_fails_before_dispatch(changes):
    with pytest.raises(ValueError):
        replace(Settings(), **changes).check_repo()


def test_runtime_closes_client_on_exception(tmp_path):
    settings = replace(Settings(), database=str(tmp_path / "live.db"))
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    with pytest.raises(RuntimeError):
        with create_runtime(settings, provider_factory=lambda s: Providers(s, client=client)):
            raise RuntimeError("worker stopped")
    assert client.is_closed


def test_scope_change_fails_startup_and_closes_client(tmp_path):
    settings = replace(Settings(), database=str(tmp_path / "live.db"))
    with create_runtime(settings):
        pass
    client = httpx.Client()
    with pytest.raises(ValueError, match="scope changed"):
        with create_runtime(
            replace(settings, repo="Nasdin/another-fork"),
            provider_factory=lambda s: Providers(s, client=client),
        ):
            pytest.fail("Scope mismatch must stop startup")
    assert client.is_closed


def test_app_factory_isolates_databases_and_closes_pool(tmp_path):
    settings = replace(Settings(), database=str(tmp_path / "live.db"))
    pool = httpx.Client()
    first = create_app(
        settings,
        demo_database=tmp_path / "first.db",
        provider_factory=lambda s: Providers(s, client=pool),
    )
    second = create_app(
        replace(settings, database=str(tmp_path / "other-live.db")),
        demo_database=tmp_path / "second.db",
    )
    with TestClient(first) as one, TestClient(second) as two:
        assert (
            one.post(
                "/api/demo/events", json={"delivery_id": "one", "title": "Example issue"}
            ).status_code
            == 200
        )
        assert len(one.get("/api/dashboard").json()["events"]) == 1
        assert two.get("/api/dashboard").json()["events"] == []
        assert not pool.is_closed
    assert pool.is_closed


def test_settings_repr_excludes_credentials():
    settings = replace(Settings(), devin_key="sensitive-key", github_token="sensitive-token")
    assert "sensitive" not in repr(settings)


def test_legacy_ledger_cannot_adopt_foreign_repository(tmp_path):
    from app.automation.store import Store

    store = Store(tmp_path / "legacy.db")
    store.enqueue("issue:Nasdin/old-fork:1", "repair", {})
    with pytest.raises(ValueError, match="scope changed"):
        store.bind_scope("Nasdin/new-fork", "main", "org")


@pytest.mark.parametrize(
    "key,repository,branch",
    [
        ("scan:Nasdin/old-fork:main:1", "Nasdin/new-fork", "main"),
        ("scan:Nasdin/superset:old-branch:1", "Nasdin/superset", "new-branch"),
        ("validation:Nasdin/old-fork:1:abc", "Nasdin/new-fork", "main"),
    ],
)
def test_legacy_scope_checks_all_available_keys(tmp_path, key, repository, branch):
    from app.automation.store import Store

    store = Store(tmp_path / "legacy.db")
    store.enqueue(key, "scan", {})
    with pytest.raises(ValueError, match="scope changed"):
        store.bind_scope(repository, branch, "org")


def test_repository_spelling_cannot_change_durable_identity(tmp_path):
    from app.automation.store import Store

    store = Store(tmp_path / "live.db")
    store.bind_scope("Nasdin/superset", "main", "org")
    with pytest.raises(ValueError, match="scope changed"):
        store.bind_scope("nasdin/superset", "main", "org")
