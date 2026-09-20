from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
import pytest
from app.automation.config import Settings
from app.automation.store import Store
from app.automation.engine import Engine
from app.automation.providers import UnknownEffect, ProviderError

SHA = "a" * 40


class FakeProvider:
    created = 0
    comments = []
    response = {}
    failure = None

    def create_session(self, payload):
        self.created += 1
        if self.failure:
            raise self.failure
        return {
            "session_id": "test-session",
            "url": "https://app.devin.ai/sessions/test-session",
        }

    def session(self, sid):
        if self.failure:
            raise self.failure
        return {"session_id": sid, **self.response}

    def pr(self, n):
        return {
            "state": "open",
            "head": {"sha": SHA},
            "base": {"repo": {"full_name": "Nasdin/superset"}, "ref": "master"},
            "html_url": f"https://github.com/Nasdin/superset/pull/{n}",
        }

    def comment(self, n, body, repository=None):
        self.comments.append((n, body))
        return {
            "id": len(self.comments),
            "html_url": f"https://github.com/Nasdin/superset/issues/{n}#comment",
        }

    def confirm_publication(self, payload, receipt):
        return f"https://github.com/Nasdin/superset/issues/{payload['number']}#comment"

    def attachments(self, sid):
        return [
            {
                "source": "devin",
                "url": f"https://attachments.devin.ai/{kind}",
                "attachment_id": kind,
                "content_type": {
                    "screenshot": "image/png",
                    "video": "video/webm",
                    "logs": "text/plain",
                    "tests": "application/json",
                }[kind],
            }
            for kind in ["screenshot", "video", "logs", "tests"]
        ]


@pytest.fixture
def setup(tmp_path):
    db = Store(tmp_path / "test.db")
    p = FakeProvider()
    p.comments = []
    s = replace(
        Settings(),
        enabled=True,
        branch="master",
        devin_key="test",
        github_token="test",
        database=str(tmp_path / "test.db"),
    )
    return db, p, Engine(s, db, p)


def repair(db):
    return db.enqueue("issue:1", "repair", {"issue_number": 1, "base_sha": SHA})


def test_atomic_claim_allows_one_dispatch(setup):
    db, p, e = setup
    for n in range(8):
        db.enqueue(f"issue:{n}", "repair", {"issue_number": n, "base_sha": SHA})
    with ThreadPoolExecutor(8) as pool:
        claimed = list(pool.map(lambda _: db.claim(), range(8)))
    assert sum(j is not None for j in claimed) == 1


def test_creation_timeout_never_blindly_retries(setup):
    db, p, e = setup
    job = repair(db)
    p.failure = UnknownEffect("timeout")
    e.tick()
    e.tick()
    assert db.get(job["id"])["state"] == "unknown_effect"
    assert p.created == 1


def test_crash_during_dispatch_requires_reconciliation(setup):
    db, p, e = setup
    job = repair(db)
    db.claim()
    db.update(job["id"], lease_until=0)
    assert e.tick() is None
    assert db.get(job["id"])["state"] == "unknown_effect"
    assert p.created == 0


def test_poll_timeout_does_not_terminate_or_restart(setup):
    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    p.failure = ProviderError("Read timeout")
    e.tick()
    assert db.get(job["id"])["state"] == "running"
    assert p.created == 1


def test_repair_waits_for_integration_batch(setup):
    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    p.response = {
        "status": "running",
        "status_detail": "finished",
        "structured_output": {
            "pr_url": "https://github.com/Nasdin/superset/pull/2",
            "summary": "fix",
            "tests": [],
            "blocker": "",
        },
    }
    e.tick()
    assert db.get(job["id"])["state"] == "implemented"
    assert not any(j["kind"] == "validation" for j in db.jobs())
    e.s = replace(e.s, batch_seconds=0)
    batch = e.schedule_batch()
    assert batch["kind"] == "integration"
    assert batch["payload"]["members"][0]["sha"] == SHA
    assert e.schedule_batch() is None


@pytest.mark.parametrize(
    "status,detail,complete,expected",
    [
        ("running", "waiting_for_user", True, "implemented"),
        ("running", "waiting_for_user", False, "needs_attention"),
        ("running", "waiting_for_user", None, "needs_attention"),
        ("running", "waiting_for_user", 1, "needs_attention"),
        ("running", "waiting_for_user", "true", "needs_attention"),
        ("running", "waiting_for_approval", True, "needs_attention"),
        ("running", "working", True, "running"),
        ("suspended", "waiting_for_user", True, "needs_attention"),
    ],
)
def test_explicit_handoff_does_not_bypass_session_state(
    setup, status, detail, complete, expected
):
    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    result = {
        "pr_url": "https://github.com/Nasdin/superset/pull/2",
        "summary": "Fix prepared, independent validation still required",
        "tests": ["regression passed"],
        "blocker": "",
    }
    if complete is not None:
        result["task_complete"] = complete
    p.response = {
        "status": status,
        "status_detail": detail,
        "structured_output": result,
    }
    e.tick()
    assert db.get(job["id"])["state"] == expected
    assert not any(j["state"] == "review_ready" for j in db.jobs())
    assert p.created == 1


def test_explicit_handoff_still_checks_pr_target(setup):
    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    p.response = {
        "status": "running",
        "status_detail": "waiting_for_user",
        "structured_output": {
            "task_complete": True,
            "pr_url": "https://github.com/apache/superset/pull/2",
            "blocker": "",
        },
    }
    e.tick()
    assert db.get(job["id"])["state"] == "needs_attention"
    assert not db.publications()


def test_repair_handoff_with_pr_and_blocker_never_advances(setup):
    db, p, e = setup
    job = repair(db)
    e.finish_repair(
        job,
        {
            "task_complete": True,
            "pr_url": "https://github.com/Nasdin/superset/pull/2",
            "blocker": "Candidate regression still fails",
        },
    )
    assert db.get(job["id"])["state"] == "needs_attention"
    assert not db.publications()


def validation(db):
    parent = repair(db)
    db.update(parent["id"], session_id="implementation", state="implemented")
    job = db.enqueue(
        "validate:2",
        "validation",
        {"issue_number": 1},
        parent_id=parent["id"],
        candidate_sha=SHA,
        pr_number=2,
    )
    db.update(
        job["id"],
        session_id="independent",
        session_url="https://app.devin.ai/sessions/independent",
        state="running",
    )
    return db.get(job["id"])


def result():
    return {
        "candidate_sha": SHA,
        "passed": True,
        "summary": "All checked",
        "blocker": "",
        "checks": [
            {"name": n, "passed": True, "command": "test", "detail": "ok"}
            for n in ["services", "database", "browser", "regression"]
        ],
        "artifacts": [
            {"kind": k, "name": k, "url": f"https://attachments.devin.ai/{k}"}
            for k in ["screenshot", "video", "logs", "tests"]
        ],
    }


def test_missing_video_fails_gate_and_reports_truth(setup):
    db, p, e = setup
    job = validation(db)
    r = result()
    r["artifacts"] = r["artifacts"][::2]
    e.finish_validation(job, r)
    assert db.get(job["id"])["state"] == "validation_failed"
    e.flush_publication()
    e.flush_publication()
    assert len(p.comments) == 2


def test_unknown_artifact_url_never_counts_as_evidence(setup):
    db, p, e = setup
    job = validation(db)
    r = result()
    r["artifacts"][0]["url"] = "https://attacker.example/screenshot"
    e.finish_validation(job, r)
    assert db.get(job["id"])["state"] == "validation_failed"
    assert "attacker.example" not in str(p.comments)


def test_valid_independent_manifest_reaches_human_review(setup):
    db, p, e = setup
    job = validation(db)
    e.finish_validation(job, result())
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "review_ready"
    e.flush_publication()
    e.flush_publication()
    e.flush_publication()
    assert len(p.comments) == 2
    assert Store(db.path).recall("repository_lessons")[0]["candidate_sha"] == SHA


def test_same_validator_as_implementer_fails(setup):
    db, p, e = setup
    job = validation(db)
    job["session_id"] = "implementation"
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "validation_failed"


def test_wrong_revision_is_rejected(setup):
    db, p, e = setup
    job = validation(db)
    job["candidate_sha"] = "b" * 40
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "stale"
    assert not p.comments


def test_total_budget_limit_prevents_dispatch(setup):
    db, p, e = setup
    job = repair(db)
    e.s = replace(e.s, max_sessions=0)
    e.tick()
    assert db.get(job["id"])["state"] == "blocked"
    assert p.created == 0


def test_reused_attachment_cannot_satisfy_four_types(setup):
    db, p, e = setup
    job = validation(db)
    r = result()
    for a in r["artifacts"]:
        a["url"] = "https://attachments.devin.ai/logs"
    e.finish_validation(job, r)
    assert db.get(job["id"])["state"] == "validation_failed"


@pytest.mark.parametrize("mutation", ["failure", "blocker"])
def test_contradictory_validation_cannot_pass(setup, mutation):
    db, p, e = setup
    job = validation(db)
    r = result()
    if mutation == "blocker":
        r["blocker"] = "Could not start Superset"
    else:
        r["checks"].append(
            {
                "name": "regression",
                "passed": False,
                "command": "pytest",
                "detail": "failed",
            }
        )
    e.finish_validation(job, r)
    assert db.get(job["id"])["state"] == "validation_failed"


def test_outbox_survives_process_restart(setup):
    db, p, e = setup
    job = validation(db)
    e.finish_validation(job, result())
    assert len(db.publications()) == 2 and not p.comments
    restarted = Engine(e.s, Store(db.path), p)
    restarted.flush_publication()
    restarted.flush_publication()
    assert len(p.comments) == 2
    assert all(x["state"] == "sent" for x in db.publications())


def test_queue_age_does_not_consume_session_timeout(setup):
    db, p, e = setup
    job = repair(db)
    with db.connect() as c:
        c.execute(
            "UPDATE jobs SET created=? WHERE id=?", (time.time() - 999999, job["id"])
        )
    e.tick()
    db.update(job["id"], next_poll=0)
    p.response = {"status": "running", "status_detail": "working"}
    e.tick()
    assert db.get(job["id"])["state"] == "running"


def test_later_pr_push_invalidates_ready_evidence(setup):
    db, p, e = setup
    job = validation(db)
    e.finish_validation(job, result())
    original = p.pr

    def changed(n):
        response = original(n)
        response["head"]["sha"] = "b" * 40
        return response

    p.pr = changed
    e.refresh_readiness()
    assert db.get(job["id"])["state"] == "stale"
    assert any(
        j["candidate_sha"] == "b" * 40 and j["state"] == "queued" for j in db.jobs()
    )


def test_schedule_disabled_still_allows_manual_scan(setup):
    db, p, e = setup
    e.s = replace(e.s, scan_interval=0)
    p.gh = lambda *a, **kw: {"sha": SHA}
    assert e.schedule_scan()["kind"] == "scan"


def test_intake_outage_does_not_skip_provider_poll(setup):
    from app.automation.worker import cycle

    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    p.response = {"status": "running", "status_detail": "working"}
    e.s = replace(e.s, scan_interval=0)
    p.gh = lambda *a, **kw: (_ for _ in ()).throw(ProviderError("outage"))
    cycle(e)
    assert db.get(job["id"])["next_poll"] > time.time()
    assert db.recall("worker_status")["state"] == "degraded"


def test_integration_never_merges_default_or_release_branch(setup):
    db, p, e = setup
    j = repair(db)
    db.update(
        j["id"],
        state="implemented",
        pr_number=2,
        candidate_sha=SHA,
        session_id="implementation",
    )
    e.s = replace(e.s, batch_seconds=0)
    batch = e.schedule_batch()
    mutations = []

    def github(method, path, **kwargs):
        if method == "GET":
            if "/git/ref/" in path:
                raise ProviderError("Not found", 404)
            if path.endswith("/pulls"):
                return []
            return {"sha": "c" * 40}
        mutations.append((path, kwargs["json"]))
        if path.endswith("/merges"):
            return {"sha": "d" * 40}
        if path.endswith("/pulls"):
            return {
                "number": 3,
                "html_url": "https://github.com/Nasdin/superset/pull/3",
            }
        return {}

    p.gh = github
    e.assemble_candidate(batch)
    assert all(
        body["base"].startswith("cognition/integration/")
        for path, body in mutations
        if path.endswith("/merges")
    )
    val = next(j for j in db.jobs() if j["kind"] == "validation")
    assert val["candidate_sha"] == "d" * 40 and val["pr_number"] == 3
    assert val["payload"]["implementation_jobs"] == [j["id"]]


@pytest.mark.parametrize("lost_at", ["refs", "merges", "pulls"])
def test_integration_recovers_lost_write_responses_without_duplicates(setup, lost_at):
    db, p, engine = setup
    implementation = repair(db)
    db.update(
        implementation["id"],
        state="implemented",
        pr_number=2,
        candidate_sha=SHA,
        session_id="implementation",
    )
    engine.s = replace(engine.s, batch_seconds=0, max_sessions=2)
    job = engine.schedule_batch()
    remote = {"head": None, "pr": None}
    writes = {"refs": 0, "merges": 0, "pulls": 0}
    base, integrated = "c" * 40, "d" * 40
    branch = "cognition/integration/" + job["id"][:12]

    def github(method, path, **kwargs):
        action = path.rsplit("/", 1)[-1]
        if method == "GET":
            if "/git/ref/" in path:
                if remote["head"] is None:
                    raise ProviderError("Not found", 404)
                return {"object": {"sha": remote["head"]}}
            if "/git/commits/" in path:
                return {"parents": [{"sha": base}, {"sha": SHA}]}
            if path.endswith("/pulls"):
                return [remote["pr"]] if remote["pr"] else []
            return {"sha": base}
        writes[action] += 1
        if action == "refs":
            remote["head"] = base
            response = {}
        elif action == "merges":
            remote["head"] = integrated
            response = {"sha": integrated}
        else:
            remote["pr"] = {
                "number": 3,
                "html_url": "https://github.com/Nasdin/superset/pull/3",
                "state": "open",
                "head": {"sha": integrated, "ref": branch},
            }
            response = remote["pr"]
        if action == lost_at and writes[action] == 1:
            raise UnknownEffect("Response lost after successful mutation")
        return response

    p.gh = github
    engine.tick()
    assert db.get(job["id"])["state"] == "unknown_effect"
    db.update(job["id"], state="queued")
    engine.tick()
    assert db.get(job["id"])["state"] == "integrated"
    assert writes == {"refs": 1, "merges": 1, "pulls": 1}
    engine.tick()
    validator = next(j for j in db.jobs() if j["kind"] == "validation")
    assert validator["state"] == "running"
    assert validator["candidate_sha"] == integrated
    assert p.created == 1


def test_repair_reserves_a_slot_for_fresh_validation(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.s = replace(engine.s, max_sessions=1)
    engine.tick()
    assert db.get(job["id"])["state"] == "blocked"
    assert provider.created == 0


def test_report_readback_failure_never_resends_acknowledged_comment(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.publish(job["id"], 1, "A report with evidence links")
    original = provider.confirm_publication
    provider.confirm_publication = lambda *args: (_ for _ in ()).throw(
        ProviderError("Readback unavailable")
    )
    engine.flush_publication()
    assert db.publications()[0]["state"] == "delivered"
    assert len(provider.comments) == 1
    restarted = Engine(engine.s, Store(db.path), provider)
    provider.confirm_publication = original
    restarted.flush_publication()
    assert db.publications()[0]["state"] == "sent"
    assert len(provider.comments) == 1


def test_crash_during_confirmation_recovers_without_resend(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.publish(job["id"], 1, "Report")
    item = db.claim_publication()
    db.finish_publication(item["key"], "confirming", receipt={"id": 123})
    with db.connect() as connection:
        connection.execute("UPDATE publications SET updated=?", (time.time() - 181,))
    engine.flush_publication()
    assert db.publications()[0]["state"] == "sent"
    assert provider.comments == []


def test_crash_before_receipt_is_not_automatically_resent(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.publish(job["id"], 1, "Report")
    db.claim_publication()
    with db.connect() as connection:
        connection.execute("UPDATE publications SET updated=?", (time.time() - 181,))
    engine.flush_publication()
    assert db.publications()[0]["state"] == "unknown_effect"
    assert provider.comments == []


def test_slack_uses_saved_destination_and_provider_permalink(setup):
    db, provider, engine = setup
    engine.s = replace(engine.s, slack_channel="C_ORIGINAL")
    job = {**repair(db), "pr_number": 2}
    engine.publish_slack(job, "Evidence")
    engine.s = replace(engine.s, slack_channel="C_CHANGED")
    sent = []

    def slack(text, key, channel):
        sent.append(channel)
        return {"channel": channel, "ts": "123.456"}

    def confirm(payload, receipt):
        assert payload["channel"] == receipt["channel"] == "C_ORIGINAL"
        return "https://takehome.slack.com/archives/C_ORIGINAL/p123456"

    provider.slack = slack
    provider.confirm_publication = confirm
    engine.flush_publication()
    assert sent == ["C_ORIGINAL"]
    assert (
        db.publications()[0]["url"]
        == "https://takehome.slack.com/archives/C_ORIGINAL/p123456"
    )
