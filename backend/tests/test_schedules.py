import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from app.automation import routes
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.providers import UnknownEffect
from app.automation.schedules import ScheduleConflict, ScheduleService
from app.automation.store import Store
from app.main import create_app
from fastapi.testclient import TestClient
from test_automation import SHA, FakeProvider


@pytest.fixture
def setup(tmp_path):
    settings = replace(
        Settings(),
        database=str(tmp_path / "jobs.db"),
        enabled=True,
        devin_key="test",
        github_token="test",
        operator_token="operator",
    )
    store = Store(settings.database)
    provider = FakeProvider()
    provider.gh = lambda *args, **kwargs: {"sha": SHA}
    service = ScheduleService(settings, store, provider)
    return settings, store, provider, service


def test_parallel_manual_intents_are_idempotent_and_distinct_from_schedule(setup):
    _, store, _, service = setup
    token = str(uuid4())
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: service.run_now(token), range(4)))
    assert len({j["id"] for j in jobs}) == 1
    assert jobs[0]["payload"]["source"] == "manual"
    assert jobs[0]["payload"]["base_sha"] == SHA
    with pytest.raises(ScheduleConflict):
        service.run_now(str(uuid4()))
    store.update(jobs[0]["id"], state="completed")
    assert service.run_now(token)["id"] == jobs[0]["id"]
    assert service.run_now(str(uuid4()))["id"] != jobs[0]["id"]


def test_schedule_persists_pause_and_updates_without_immediate_paid_work(setup):
    settings, store, provider, service = setup
    first = service.schedule()
    changed = service.configure(False, 3600, first["updated"])
    assert service.tick() is None
    # A new process reads persisted settings instead of resetting from environment.
    again = ScheduleService(settings, Store(settings.database), provider)
    assert again.schedule()["enabled"] == 0
    with pytest.raises(ScheduleConflict):
        again.configure(True, 86400, first["updated"])
    enabled = again.configure(True, 3600, changed["updated"])
    assert enabled["next_run"] > time.time() + 3590
    assert again.tick() is None
    assert store.jobs() == []


def test_schedule_coalesces_downtime_and_respects_existing_scan(setup):
    _, store, _, service = setup
    service.schedule()
    with store.connect() as c:
        c.execute("UPDATE schedules SET next_run=1")
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: service.tick(), range(4)))
    assert len(store.jobs()) == 1
    assert store.jobs()[0]["payload"]["source"] == "schedule"
    assert service.schedule()["next_run"] > time.time()
    with store.connect() as c:
        c.execute("UPDATE schedules SET next_run=1")
    assert service.tick()["id"] == store.jobs()[0]["id"]
    assert len(store.jobs()) == 1


def test_disabled_schedule_still_allows_manual_intent(setup):
    settings, store, provider, _ = setup
    service = ScheduleService(replace(settings, scan_interval=0), store, provider)
    assert service.tick() is None
    assert service.run_now(str(uuid4()))["payload"]["source"] == "manual"


def client_for(settings, store, provider, tmp_path):
    app = create_app(settings, demo_database=tmp_path / "demo.db")
    engine = Engine(settings, store, provider)
    app.dependency_overrides[routes.get_engine] = lambda: engine
    return TestClient(app)


def test_manual_routes_reject_reviewers_and_invalid_requests(setup, tmp_path):
    settings, store, provider, _ = setup
    client = client_for(settings, store, provider, tmp_path)
    payload = {"request_id": str(uuid4())}
    for path in ["scan", "validate", "schedules/discovery"]:
        assert client.post("/api/live/" + path, json=payload).status_code == 401
    auth = {"Authorization": "Bearer operator"}
    assert client.get("/api/live/operator", headers=auth).status_code == 200
    assert (
        client.post("/api/live/scan", headers=auth, json={"request_id": "invalid"}).status_code
        == 422
    )
    first = client.post("/api/live/scan", headers=auth, json=payload)
    assert first.status_code == 200
    assert (
        client.post("/api/live/scan", headers=auth, json=payload).json()["id"] == first.json()["id"]
    )
    assert len(store.jobs()) == 1
    view = client.get("/api/live/automations").json()
    assert view["history"][0]["id"] == first.json()["id"]
    assert view["schedule"]["name"] and len(view["triggers"]) == 3


def test_uncertain_resume_blocks_repeated_message(setup, tmp_path):
    settings, store, provider, _ = setup
    job = store.enqueue("resume-test", "repair", {"issue_number": 1})
    store.update(
        job["id"],
        state="needs_attention",
        session_id="existing",
        session_url="https://app.devin.ai/sessions/existing",
    )
    provider.response = {"status": "suspended", "tags": ["cognition-job:" + job["id"]]}
    calls = []

    def send(*args, **kwargs):
        calls.append(args)
        raise UnknownEffect("Response lost")

    provider.devin = send
    client = client_for(settings, store, provider, tmp_path)
    path = f"/api/live/jobs/{job['id']}/resume"
    auth = {"Authorization": "Bearer operator"}
    payload = {"request_id": str(uuid4())}
    assert client.post(path, headers=auth, json=payload).status_code == 409
    assert client.post(path, headers=auth, json=payload).json()["status"] == "unknown_effect"
    assert client.post(path, headers=auth, json={"request_id": str(uuid4())}).status_code == 409
    assert len(calls) == 1
    assert store.get(job["id"])["state"] == "unknown_effect"


def test_resume_preserves_session_identity_and_resets_wall_timeout(setup, tmp_path):
    settings, store, provider, _ = setup
    job = store.enqueue("resume-test", "repair", {"issue_number": 1})
    store.update(
        job["id"],
        state="needs_attention",
        session_id="existing",
        started=1,
        session_url="https://app.devin.ai/sessions/existing",
    )
    provider.response = {"status": "suspended", "tags": ["cognition-job:" + job["id"]]}
    provider.devin = lambda *args, **kwargs: {"session_id": "existing", "status": "resuming"}
    client = client_for(settings, store, provider, tmp_path)
    response = client.post(
        f"/api/live/jobs/{job['id']}/resume",
        headers={"Authorization": "Bearer operator"},
        json={"request_id": str(uuid4())},
    )
    assert response.status_code == 200
    updated = store.get(job["id"])
    assert updated["state"] == "running" and updated["session_id"] == "existing"
    assert updated["started"] > time.time() - 10
    assert len(store.jobs()) == 1
