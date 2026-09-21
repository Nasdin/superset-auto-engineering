import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.providers import ProviderError, UnknownEffect
from app.automation.store import Store

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
                    "api": "text/plain",
                    "coverage": "application/json",
                }[kind],
            }
            for kind in ["screenshot", "video", "logs", "tests", "api", "coverage"]
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
    e.settings = replace(e.settings, batch_seconds=0)
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
def test_explicit_handoff_does_not_bypass_session_state(setup, status, detail, complete, expected):
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
        "evidence_version": 2,
        "api_requests": [
            {
                "name": "SQL query",
                "method": "POST",
                "url": "http://localhost:8088/api/v1/sqllab/execute/",
                "curl": "curl -X POST http://localhost:8088/api/v1/sqllab/execute/",
                "expected_status": 200,
                "actual_status": 200,
                "assertion": "query result equals fixture",
                "response_excerpt": '{"data":[{"value":1}]}',
                "passed": True,
                "evidence_url": "https://attachments.devin.ai/api",
            }
        ],
        "coverage": {
            "command": "pytest --cov=superset.db_engine_specs.mysql",
            "scope": "superset.db_engine_specs.mysql",
            "lines_covered": 80,
            "lines_total": 100,
            "branches_covered": 10,
            "branches_total": 20,
            "report_url": "https://attachments.devin.ai/coverage",
        },
        "test_results": {
            "command": "pytest regression",
            "passed": 9,
            "failed": 0,
            "skipped": 0,
            "report_url": "https://attachments.devin.ai/tests",
        },
        "blocker": "",
        "checks": [
            {"name": n, "passed": True, "command": "test", "detail": "ok"}
            for n in ["services", "database", "browser", "regression", "api", "coverage"]
        ],
        "artifacts": [
            {"kind": k, "name": k, "url": f"https://attachments.devin.ai/{k}"}
            for k in ["screenshot", "video", "logs", "tests", "api", "coverage"]
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
    e.settings = replace(e.settings, max_sessions=0)
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
    restarted = Engine(e.settings, Store(db.path), p)
    restarted.flush_publication()
    restarted.flush_publication()
    assert len(p.comments) == 2
    assert all(x["state"] == "sent" for x in db.publications())


def test_queue_age_does_not_consume_session_timeout(setup):
    db, p, e = setup
    job = repair(db)
    with db.connect() as c:
        c.execute(
            "UPDATE jobs SET created=:p0 WHERE id=:p1",
            {"p0": time.time() - 999999, "p1": job["id"]},
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
    assert any(j["candidate_sha"] == "b" * 40 and j["state"] == "queued" for j in db.jobs())


def test_schedule_disabled_still_allows_manual_scan(setup):
    db, p, e = setup
    e.settings = replace(e.settings, scan_interval=0)
    p.gh = lambda *a, **kw: {"sha": SHA}
    from app.automation.schedules import ScheduleService

    assert e.schedule_scan() is None
    assert ScheduleService(e.settings, db, p).run_now("manual-test")["kind"] == "scan"


def test_intake_outage_does_not_skip_provider_poll(setup):
    from app.automation.worker import cycle

    db, p, e = setup
    job = repair(db)
    e.tick()
    db.update(job["id"], next_poll=0)
    p.response = {"status": "running", "status_detail": "working"}
    e.settings = replace(e.settings, scan_interval=0)
    p.gh = lambda *a, **kw: (_ for _ in ()).throw(ProviderError("outage"))
    cycle(e)
    assert db.get(job["id"])["next_poll"] > time.time()
    assert db.recall("worker_status")["state"] == "degraded"


@pytest.mark.parametrize("interrupt_handoff", [False, True])
def test_integration_never_merges_default_or_release_branch(setup, monkeypatch, interrupt_handoff):
    db, p, e = setup
    j = repair(db)
    db.update(
        j["id"],
        state="implemented",
        pr_number=2,
        candidate_sha=SHA,
        session_id="implementation",
    )
    e.settings = replace(e.settings, batch_seconds=0)
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
    if interrupt_handoff:
        enqueue = db._enqueue

        def fail_after_child(*args, **kwargs):
            enqueue(*args, **kwargs)
            raise RuntimeError("Interrupted before handoff commit")

        monkeypatch.setattr(db, "_enqueue", fail_after_child)
        with pytest.raises(RuntimeError, match="Interrupted"):
            e.assemble_candidate(batch)
        assert db.get(batch["id"])["state"] == "queued"
        assert not any(job["kind"] == "validation" for job in db.jobs())
        monkeypatch.setattr(db, "_enqueue", enqueue)
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
    engine.settings = replace(engine.settings, batch_seconds=0, max_sessions=2)
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
    component_pr = p.pr
    p.pr = lambda number: {**component_pr(number), **(remote["pr"] if number == 3 else {})}
    engine.tick()
    validator = next(j for j in db.jobs() if j["kind"] == "validation")
    assert validator["state"] == "running"
    assert validator["candidate_sha"] == integrated
    assert p.created == 1


def test_repair_reserves_a_slot_for_fresh_validation(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.settings = replace(engine.settings, max_sessions=1)
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
    restarted = Engine(engine.settings, Store(db.path), provider)
    provider.confirm_publication = original
    restarted.flush_publication()
    assert db.publications()[0]["state"] == "delivered"  # Backoff survives restart.
    with db.connect() as c:
        c.execute("UPDATE recovery SET next_retry=0")
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
        connection.execute("UPDATE publications SET updated=:p0", {"p0": time.time() - 181})
    engine.flush_publication()
    assert db.publications()[0]["state"] == "sent"
    assert provider.comments == []


def test_crash_before_receipt_is_not_automatically_resent(setup):
    db, provider, engine = setup
    job = repair(db)
    engine.publish(job["id"], 1, "Report")
    db.claim_publication()
    with db.connect() as connection:
        connection.execute("UPDATE publications SET updated=:p0", {"p0": time.time() - 181})
    engine.flush_publication()
    assert db.publications()[0]["state"] == "unknown_effect"
    assert provider.comments == []


def test_slack_uses_saved_destination_and_provider_permalink(setup):
    db, provider, engine = setup
    engine.settings = replace(engine.settings, slack_channel="C_ORIGINAL")
    job = {**repair(db), "pr_number": 2}
    engine.publish_slack(job, "Evidence")
    engine.settings = replace(engine.settings, slack_channel="C_CHANGED")
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
    assert db.publications()[0]["url"] == "https://takehome.slack.com/archives/C_ORIGINAL/p123456"


def test_moved_pr_during_validation_schedules_exact_replacement_once(setup):
    db, p, e = setup
    job = validation(db)
    original = p.pr
    p.pr = lambda number: {**original(number), "head": {"sha": "b" * 40}}
    e.finish_validation(job, result())
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "stale"
    replacements = [j for j in db.jobs() if j["candidate_sha"] == "b" * 40]
    assert len(replacements) == 1
    assert replacements[0]["session_id"] is None
    assert not db.publications()


def test_old_implemented_job_remains_eligible_beyond_dashboard_limit(setup):
    db, p, e = setup
    job = repair(db)
    db.update(job["id"], state="implemented", candidate_sha=SHA, pr_number=2)
    for number in range(101):
        newer = db.enqueue(f"scan:{number}", "scan", {})
        db.update(newer["id"], state="completed")
    assert len(db.jobs()) == 100
    e.settings = replace(e.settings, batch_seconds=0)
    batch = e.schedule_batch()
    assert batch["payload"]["members"][0]["job_id"] == job["id"]
    assert e.schedule_batch() is None


def test_metrics_count_all_history_not_only_dashboard_page(setup):
    db, p, e = setup
    job = repair(db)
    db.update(job["id"], session_id="real-session", acu=3.5, state="implemented")
    for number in range(101):
        db.enqueue(f"scan:{number}", "scan", {})
    assert db.metrics()["sessions"] == 1
    assert db.metrics()["acu"] == 3.5


def test_scope_cannot_redirect_queued_jobs_on_restart(setup):
    db, p, e = setup
    repair(db)
    for change in [{"repo": "Nasdin/other"}, {"branch": "another-branch"}, {"org": "other-org"}]:
        with pytest.raises(ValueError, match="scope changed"):
            Engine(replace(e.settings, **change), Store(db.path), p)
    assert p.created == 0


def test_replacement_and_invalidation_roll_back_together(setup):
    from sqlalchemy.exc import IntegrityError

    db, p, e = setup
    job = validation(db)
    before = len(db.jobs())
    with db.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_stale BEFORE UPDATE ON jobs WHEN NEW.state='stale' BEGIN SELECT RAISE(ABORT,'injected failure'); END"
        )
    with pytest.raises(IntegrityError):
        db.supersede_validation(job, "b" * 40, e.settings.repo)
    assert len(db.jobs()) == before
    assert db.get(job["id"])["state"] == "running"


def test_missing_implementation_identity_cannot_pass_gate(setup):
    db, p, e = setup
    job = validation(db)
    job["payload"]["implementation_jobs"] = ["missing-job"]
    e.finish_validation(job, result())
    assert db.get(job["id"])["state"] == "validation_failed"


def test_issue_intake_validates_scope_and_deduplicates(setup):
    db, provider, engine = setup
    issue = {
        "state": "open",
        "title": "Fix",
        "html_url": "https://github.com/Nasdin/superset/issues/1",
        "labels": [{"name": engine.settings.label}],
        "user": {"login": engine.settings.allowed_actor},
    }
    calls = []

    def github(method, path, **kwargs):
        calls.append(path)
        return {"sha": SHA} if "/commits/" in path else issue

    provider.gh = github
    first = engine.accept_issue(1, "operator")
    assert first["payload"]["base_sha"] == SHA
    assert engine.accept_issue(1, "operator")["id"] == first["id"]
    assert len(calls) == 2
    issue["user"]["login"] = "untrusted"
    with pytest.raises(ValueError, match="author"):
        engine.accept_issue(2, "operator")
    issue["labels"] = []
    with pytest.raises(ValueError, match="label"):
        engine.accept_issue(2, "operator")
    issue["state"] = "closed"
    with pytest.raises(ValueError, match="open"):
        engine.accept_issue(2, "operator")
    assert len(db.jobs()) == 1


def test_scan_reconciles_existing_finding_without_duplicate_issue(setup):
    db, provider, engine = setup
    job = db.enqueue("scan-test", "scan", {"base_sha": SHA})
    job["session_url"] = "https://app.devin.ai/sessions/discovery"
    finding = {
        "base_sha": SHA,
        "title": "Reproducible defect",
        "description": "Details",
        "reproduction": "pytest test_bug",
        "acceptance": "Regression passes",
    }
    issues = []
    posts = []

    def github(method, path, **kwargs):
        if method == "POST":
            issue = {
                **kwargs["json"],
                "number": 17,
                "state": "open",
                "html_url": "https://github.com/Nasdin/superset/issues/17",
                "user": {"login": engine.settings.allowed_actor},
                "labels": [{"name": engine.settings.label}],
            }
            issues.append(issue)
            posts.append(issue)
            return issue
        if path.endswith("/issues"):
            return issues
        if "/commits/" in path:
            return {"sha": SHA}
        return issues[0]

    provider.gh = github
    engine.finish_scan(job, {"findings": [finding]})
    assert db.get(job["id"])["state"] == "completed"
    assert db.by_key("issue:Nasdin/superset:17")["kind"] == "repair"
    # Simulate lost local finding memory after the remote issue was created.
    with db.connect() as connection:
        connection.execute("DELETE FROM memory WHERE key LIKE 'finding:%'")
    engine.finish_scan(job, {"findings": [finding]})
    assert len(posts) == 1
    engine.finish_scan(job, {"findings": [finding]})
    assert len(posts) == 1


def test_scan_rejects_unreproduced_or_out_of_scope_findings(setup):
    db, provider, engine = setup
    job = db.enqueue("scan-test", "scan", {"base_sha": SHA})
    with pytest.raises(ValueError, match="one-issue"):
        engine.finish_scan(job, {"findings": [{}, {}]})
    with pytest.raises(ValueError, match="reproduction"):
        engine.finish_scan(job, {"findings": [{"base_sha": "wrong"}]})


def test_schedule_uses_time_bucket_and_resolved_baseline(setup):
    db, provider, engine = setup
    provider.gh = lambda *args, **kwargs: {"sha": SHA}
    first = engine.schedule_scan()
    assert first["payload"]["base_sha"] == SHA
    assert engine.schedule_scan()["id"] == first["id"]


def test_return_to_previous_sha_creates_new_validation_attempt(setup):
    db, provider, engine = setup
    first = db.enqueue(
        f"validation:{engine.settings.repo}:2:{SHA}",
        "validation",
        {"issue_number": 1},
        candidate_sha=SHA,
        pr_number=2,
    )
    db.update(first["id"], state="review_ready", session_id="original-validator")
    next_sha = "b" * 40
    db.supersede_validation(first, next_sha, engine.settings.repo)
    second = db.by_key(f"validation:{engine.settings.repo}:2:{next_sha}")
    db.supersede_validation(second, SHA, engine.settings.repo)
    db.supersede_validation(second, SHA, engine.settings.repo)
    # A late retry of the original A -> B transition must not resurrect B.
    db.supersede_validation(first, next_sha, engine.settings.repo)
    jobs = db.operational_jobs()
    assert len(jobs) == 3
    fresh = next(job for job in jobs if job["state"] == "queued")
    assert fresh["candidate_sha"] == SHA
    assert fresh["session_id"] is None
    assert fresh["id"] != first["id"]
    assert db.get(first["id"])["session_id"] == "original-validator"


def test_repair_handoff_rolls_back_when_report_cannot_be_saved(setup, monkeypatch):
    from app.automation.outbox import PublicationOutbox

    db, provider, engine = setup
    job = repair(db)
    engine.tick()
    monkeypatch.setattr(
        PublicationOutbox,
        "prepare_github",
        lambda *args, **kwargs: {"key": "broken-report", "payload": object()},
    )
    with pytest.raises(TypeError):
        engine.finish_repair(
            db.get(job["id"]), {"pr_url": "https://github.com/Nasdin/superset/pull/7"}
        )
    assert db.get(job["id"])["state"] == "running"
    assert db.get(job["id"])["pr_number"] is None
    assert db.publications() == []
    assert provider.comments == []
