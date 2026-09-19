from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', tmp_path / 'test.db')
    return TestClient(main.app)

def test_dashboard_marks_fixtures(client):
    data = client.get('/api/dashboard').json()
    assert data['mode'] == 'demo'
    assert len(data['candidate']['sha']) == 40
    assert len(data['workflows']) == 5

def test_stale_sha_rejected_without_decision(client):
    result = client.post('/api/demo/decisions', json={'sha':'stale','decision':'approved','note':'reviewed'})
    assert result.status_code == 409
    assert client.get('/api/dashboard').json()['events'] == []

def test_valid_decision_persists_but_never_merges(client):
    result = client.post('/api/demo/decisions', json={'sha':main.SHA,'decision':'approved','note':'reviewed fixture'})
    assert result.json()['merged'] is False
    events = TestClient(main.app).get('/api/dashboard').json()['events']
    assert events[0]['payload']['sha'] == main.SHA
    assert events[0]['kind'] == 'demo_decision'

def test_duplicate_events_are_atomic(client):
    client.get('/api/health')
    payload={'delivery_id':'same-delivery','title':'Fix query regression'}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(lambda _:client.post('/api/demo/events',json=payload).json(),range(8)))
    assert sum(r['status']=='queued' for r in results) == 1
    assert len(client.get('/api/dashboard').json()['events']) == 1

def test_live_approval_blocked(client):
    assert client.post('/api/releases/approve').status_code == 409

def test_invalid_decisions_rejected(client):
    assert client.post('/api/demo/decisions',json={'sha':main.SHA,'decision':'merge','note':'x'}).status_code == 422
