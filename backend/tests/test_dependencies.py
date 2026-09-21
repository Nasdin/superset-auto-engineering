import copy
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.dependencies import DependencyService
from app.automation.engine import Engine
from app.automation.providers import UnknownEffect
from app.automation.store import Store
from app.automation.validation import ValidationService
from app.automation.workbench import pull_request_rows
from test_automation import FakeProvider, result

SHA = "a" * 40
NEW = "b" * 40


class BotProvider(FakeProvider):
    def __init__(self):
        self.document = {
            "number": 7,
            "title": "chore(deps): bump a dependency",
            "state": "open",
            "draft": False,
            "html_url": "https://github.com/Nasdin/superset/pull/7",
            "user": {"login": "dependabot[bot]", "type": "Bot"},
            "head": {
                "sha": SHA,
                "ref": "dependabot/pip/update",
                "repo": {"full_name": "Nasdin/superset"},
            },
            "base": {"sha": "c" * 40, "ref": "master", "repo": {"full_name": "Nasdin/superset"}},
        }
        self.comments = []
        self.created = 0
        self.requests = []

    def pr(self, n):
        assert n == 7
        return copy.deepcopy(self.document)

    def create_session(self, payload):
        self.requests.append(payload)
        data = super().create_session(payload)
        return {**data, "session_id": f"session-{self.created}"}


@pytest.fixture
def setup(tmp_path):
    db = Store(tmp_path / "bot.db")
    settings = replace(
        Settings(autonomous_remediation=False),
        branch="master",
        enabled=True,
        devin_key="test",
        github_token="test",
    )
    provider = BotProvider()
    return db, provider, Engine(settings, db, provider), DependencyService(settings, db, provider)


def prepare(db, provider, engine, service):
    job = service.accept(7, "test")
    engine.tick()
    provider.document["head"]["sha"] = NEW
    service.finish(
        db.get(job["id"]), {"pr_url": provider.document["html_url"], "candidate_sha": NEW}
    )
    return db.get(job["id"]), next(j for j in db.jobs() if j["kind"] == "validation")


def test_concurrent_events_and_poll_share_one_job(setup):
    db, p, e, service = setup
    with ThreadPoolExecutor(8) as pool:
        jobs = list(pool.map(lambda _: service.accept(7, "test"), range(8)))
    assert len({j["id"] for j in jobs}) == 1
    assert service.webhook(7, "delivery", SHA)["status"] == "accepted"
    assert service.webhook(7, "delivery", SHA)["status"] == "duplicate"
    assert len(db.jobs()) == 1


@pytest.mark.parametrize(
    "path,value",
    [
        (("state",), "closed"),
        (("draft",), True),
        (("user", "login"), "Nasdin"),
        (("user", "type"), "User"),
        (("head", "repo", "full_name"), "attacker/superset"),
        (("base", "repo", "full_name"), "apache/superset"),
        (("base", "ref"), "wrong"),
        (("head", "sha"), "not-a-sha"),
    ],
)
def test_ineligible_pr_never_starts(setup, path, value):
    db, p, e, service = setup
    obj = p.document
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(ValueError):
        service.accept(7, "test")
    assert db.jobs() == [] and p.created == 0


def test_superseded_event_ignored(setup):
    db, p, e, service = setup
    assert service.webhook(7, "old", NEW)["status"] == "ignored"
    assert not db.jobs()


def test_a_b_a_before_dispatch_can_be_intaken_again(setup):
    db, p, e, service = setup
    old = service.accept(7, "test")
    p.document["head"]["sha"] = NEW
    e.tick()
    assert db.get(old["id"])["state"] == "stale" and p.created == 0
    p.document["head"]["sha"] = SHA
    new = service.accept(7, "test")
    assert new["id"] != old["id"] and new["state"] == "queued"


def test_own_push_coalesces_then_independent_validator_posts_original_pr(setup):
    db, p, e, service = setup
    job, validation = prepare(db, p, e, service)
    assert job["state"] == "prepared"
    assert service.accept(7, "test")["id"] == validation["id"]
    assert e.schedule_batch() is None
    e.tick()
    validator = db.get(validation["id"])
    assert validator["session_id"] != job["session_id"]
    manifest = {**result(), "candidate_sha": NEW}
    e.finish_validation(validator, manifest)
    assert db.get(validator["id"])["state"] == "review_ready"
    e.flush_publication()
    e.flush_publication()
    assert len(p.comments) == 2 and all(number == 7 for number, _ in p.comments)
    assert NEW in p.comments[-1][1]
    assert all(item["state"] == "sent" for item in db.publications())
    assert "existing" in p.requests[0]["prompt"].lower()
    assert NEW in p.requests[1]["prompt"]


@pytest.mark.parametrize("change", ["closed", "retarget", "head"])
def test_changed_pr_cannot_keep_ready_evidence(setup, change):
    db, p, e, service = setup
    _, validator = prepare(db, p, e, service)
    db.update(validator["id"], state="review_ready")
    if change == "closed":
        p.document["state"] = "closed"
    elif change == "retarget":
        p.document["base"]["ref"] = "wrong"
    else:
        p.document["head"]["sha"] = "d" * 40
    e.refresh_readiness()
    assert db.get(validator["id"])["state"] == "stale"
    assert len([j for j in db.jobs() if j["state"] == "queued"]) == (1 if change == "head" else 0)


def test_reopened_same_head_gets_fresh_validation(setup):
    db, p, e, service = setup
    _, validator = prepare(db, p, e, service)
    p.document["state"] = "closed"
    assert not ValidationService(e.settings, db, p).is_current(validator)
    p.document["state"] = "open"
    service.accept(7, "reopen")
    queued = [j for j in db.jobs() if j["state"] == "queued"]
    assert (
        len(queued) == 1
        and queued[0]["kind"] == "validation"
        and queued[0]["id"] != validator["id"]
    )


def test_changed_head_before_validator_dispatch_spends_nothing(setup):
    db, p, e, service = setup
    _, validator = prepare(db, p, e, service)
    p.document["head"]["sha"] = "d" * 40
    e.tick()
    assert db.get(validator["id"])["state"] == "stale" and p.created == 1


def test_handoff_cannot_target_another_pr(setup):
    db, p, e, service = setup
    job = service.accept(7, "test")
    with pytest.raises(ValueError):
        service.finish(
            job, {"pr_url": "https://github.com/apache/superset/pull/7", "candidate_sha": SHA}
        )
    assert len(db.jobs()) == 1 and not db.publications()


def test_unknown_dispatch_never_restarts(setup):
    db, p, e, service = setup
    job = service.accept(7, "test")
    p.failure = UnknownEffect("timeout")
    e.tick()
    service.accept(7, "retry")
    Engine(e.settings, Store(db.path), p).tick()
    assert db.get(job["id"])["state"] == "unknown_effect" and p.created == 1


def test_reserves_validation_slot_and_preserves_global_attention_block(setup):
    db, p, e, service = setup
    job = service.accept(7, "test")
    e.settings = replace(e.settings, max_sessions=1)
    e.tick()
    assert db.get(job["id"])["state"] == "blocked" and p.created == 0
    db.update(job["id"], state="queued")
    other = db.enqueue("existing", "validation", {})
    db.update(other["id"], state="needs_attention")
    e.settings = replace(e.settings, max_sessions=6)
    e.tick()
    assert db.get(job["id"])["state"] == "queued" and p.created == 0


def test_poll_rotates_pages(setup):
    db, p, e, service = setup
    pages = []

    def gh(method, path, params):
        pages.append(params["page"])
        return [{"user": {"login": "human"}}] * (100 if params["page"] == 1 else 0)

    p.gh = gh
    service.poll()
    service.poll()
    assert pages == [1, 2] and db.recall("dependabot_next_page") == 1


def test_signed_pr_event_intake_uses_live_bot_identity(monkeypatch, tmp_path, setup):
    from app.automation import routes
    from app.main import create_app
    from fastapi.testclient import TestClient

    db, p, e, service = setup
    settings = replace(e.settings, webhook_secret="test-secret", database=db.path)
    app = create_app(settings, demo_database=tmp_path / "demo.db")
    app.dependency_overrides[routes.get_engine] = lambda: Engine(settings, db, p)
    body = json.dumps(
        {
            "repository": {"full_name": settings.repo},
            "sender": {"login": "dependabot[bot]"},
            "action": "synchronize",
            "pull_request": {"number": 7, "head": {"sha": SHA}},
        }
    ).encode()
    headers = {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest(),
        "X-GitHub-Delivery": "bot-delivery",
        "X-GitHub-Event": "pull_request",
    }
    client = TestClient(app)
    assert client.post("/api/live/webhooks/github", content=body).status_code == 401
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()["status"]
        == "queued"
    )
    from app.automation.inbox import Inbox

    assert not db.jobs()
    assert Inbox(Engine(settings, db, p)).tick()["state"] == "completed"
    assert (
        client.post("/api/live/webhooks/github", content=body, headers=headers).json()["status"]
        == "duplicate"
    )


def test_workbench_keeps_bot_identity_separate_from_kind(setup):
    db, p, e, service = setup
    service.accept(7, "test")
    rows = pull_request_rows(
        [
            {"number": 8, "title": "chore: bump dependency", "labels": [], "author": "human"},
            {"number": 9, "title": "feat: a feature", "labels": [], "author": "human"},
            {"number": 10, "title": "fix: a bug", "labels": [], "author": "human"},
        ],
        db.jobs(),
        [],
    )
    assert {row["number"]: row["category"] for row in rows} == {
        7: "dependency",
        8: "dependency",
        9: "feature",
        10: "fix",
    }
    assert [row["number"] for row in rows if row["dependabot"]] == [7]


def test_workbench_api_filters_and_paginates_fork_only(setup, tmp_path):
    from app.analytics.store import AnalyticsStore
    from app.automation import routes
    from app.main import create_app
    from fastapi.testclient import TestClient

    db, p, e, service = setup
    app = create_app(e.settings, demo_database=tmp_path / "demo.db")
    app.dependency_overrides[routes.get_engine] = lambda: e
    app.state.analytics = AnalyticsStore(tmp_path / "analytics.db")
    records = [
        {
            "number": n,
            "title": "feat: feature",
            "html_url": f"https://github.com/Nasdin/superset/pull/{n}",
            "user": {"login": "human"},
            "labels": [],
            "base": {"ref": "master"},
            "state": "open",
        }
        for n in range(100, 155)
    ]
    app.state.analytics.upsert(e.settings.repo, records)
    app.state.analytics.upsert("apache/superset", [{**records[0], "number": 999}])
    service.accept(7, "test")
    client = TestClient(app)
    first = client.get("/api/live/pull-requests?kind=feature").json()
    assert first["total"] == 55 and len(first["rows"]) == 50
    assert len(client.get("/api/live/pull-requests?kind=feature&offset=50").json()["rows"]) == 5
    assert client.get("/api/live/pull-requests?bot_only=true").json()["rows"][0]["number"] == 7
    assert client.get("/api/live/pull-requests?search=999").json()["total"] == 0
    assert client.get("/api/live/pull-requests?offset=-1").status_code == 422


def test_workbench_connects_component_pr_to_integrated_validation(setup):
    db, p, e, service = setup
    validation = db.enqueue(
        "integration-validation",
        "validation",
        {"source": "integration", "members": [{"pr_number": 2}]},
        pr_number=4,
        candidate_sha=SHA,
    )
    publications = [{"key": f"github:{validation['id']}:{n}", "state": "sent"} for n in [1, 2, 4]]
    publications.append(
        {"key": f"github:validation-status-v2:{validation['id']}:4", "state": "sent"}
    )
    rows = {r["number"]: r for r in pull_request_rows([], db.jobs(), publications)}
    assert set(rows) == {2, 4}
    assert rows[2]["runs"][0]["pr_number"] == 4
    assert rows[2]["runs"][0]["candidate_sha"] == SHA
    assert [p["key"] for p in rows[2]["publications"]] == [f"github:{validation['id']}:2"]
    assert [p["key"] for p in rows[4]["publications"]] == [
        f"github:{validation['id']}:4",
        f"github:validation-status-v2:{validation['id']}:4",
    ]


def test_preparation_cannot_queue_validation_without_its_report(setup, monkeypatch):
    from app.automation.outbox import PublicationOutbox

    db, provider, engine, service = setup
    job = service.accept(7, "test")
    engine.tick()
    provider.document["head"]["sha"] = NEW
    monkeypatch.setattr(
        PublicationOutbox,
        "prepare_github",
        lambda *args, **kwargs: {"key": "broken-report", "payload": object()},
    )
    with pytest.raises(TypeError):
        service.finish(
            db.get(job["id"]), {"pr_url": provider.document["html_url"], "candidate_sha": NEW}
        )
    assert db.get(job["id"])["state"] == "running"
    assert len(db.jobs()) == 1
    assert db.publications() == []
    assert provider.comments == []
