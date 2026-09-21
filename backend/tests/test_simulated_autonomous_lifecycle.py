"""Simulated providers only: full durable worker lifecycle, not live Devin evidence.

No network or real credentials are used. The fake provider supplies synthetic
findings, commits, checks and evidence. This proves orchestration/state-machine
behavior; it does not prove that a real Devin session fixed or tested Superset.
"""

import copy
import time
from collections import Counter

from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.providers import ProviderError
from app.automation.store import Store
from app.automation.worker import cycle
from test_automation import FakeProvider, result

BASE, IMPLEMENTED, INTEGRATED, REMEDIATED = (letter * 40 for letter in "abcd")
REPOSITORY = "Simulated/superset"
BRANCH = "test-release"


class SimulatedProviders(FakeProvider):
    """In-memory remote services with persistent identity across worker restarts."""

    def __init__(self):
        self.sessions = {}
        self.session_payloads = {}
        self.issues = {}
        self.pulls = {}
        self.refs = {}
        self.comments = []
        self.remote_effects = Counter()

    def pull(self, number, sha, branch, *, draft=False):
        return {
            "number": number,
            "title": "fix: simulated regression",
            "state": "open",
            "draft": draft,
            "user": {"login": "Simulated", "type": "User"},
            "labels": [],
            "html_url": f"https://github.com/{REPOSITORY}/pull/{number}",
            "head": {"ref": branch, "sha": sha, "repo": {"full_name": REPOSITORY}},
            "base": {"ref": BRANCH, "sha": BASE, "repo": {"full_name": REPOSITORY}},
        }

    def pr(self, number):
        return copy.deepcopy(self.pulls[number])

    def create_session(self, payload):
        identity = f"simulated-session-{len(self.sessions) + 1}"
        kind = (
            "scan"
            if "findings" in payload["structured_output_schema"]["properties"]
            else payload["title"].split()[1]
        )
        self.sessions[identity] = {"kind": kind, "completed": False}
        self.session_payloads[identity] = copy.deepcopy(payload)
        self.remote_effects[f"devin_session:{kind}"] += 1
        return {"session_id": identity, "url": f"https://app.devin.ai/sessions/{identity}"}

    def session(self, identity):
        session = self.sessions[identity]
        if not session["completed"]:
            kind = session["kind"]
            if kind == "scan":
                handoff = {
                    "task_complete": True,
                    "summary": "Simulated finding for orchestration verification only",
                    "blocker": "",
                    "findings": [
                        {
                            "title": "Simulated duplicate query execution",
                            "description": "Synthetic regression used by the provider-contract test.",
                            "base_sha": BASE,
                            "reproduction": "Simulated regression test: expected 1 call, observed 2.",
                            "acceptance": "Execute once and preserve the query result.",
                        }
                    ],
                }
            elif kind == "repair":
                self.pulls[2] = self.pull(2, IMPLEMENTED, "simulated/devin-fix")
                self.remote_effects["devin_implementation_pr"] += 1
                handoff = {
                    "task_complete": True,
                    "pr_url": self.pulls[2]["html_url"],
                    "summary": "Simulated implementation",
                    "tests": ["synthetic regression"],
                    "blocker": "",
                }
            elif kind == "remediation":
                self.pulls[3]["head"]["sha"] = REMEDIATED
                self.remote_effects["devin_remediation_push"] += 1
                handoff = {
                    "task_complete": True,
                    "pr_url": self.pulls[3]["html_url"],
                    "candidate_sha": REMEDIATED,
                    "metadata_only": False,
                    "summary": "Simulated CI fix",
                    "tests": ["synthetic CI regression"],
                    "blocker": "",
                }
            else:
                assert kind == "validation"
                handoff = {
                    **result(),
                    "task_complete": True,
                    "candidate_sha": REMEDIATED,
                    "summary": "Synthetic passing evidence, not a real Superset execution",
                }
            session.update(completed=True, handoff=handoff)
        return {
            "session_id": identity,
            "status": "running",
            "status_detail": "finished",
            "tags": self.session_payloads[identity]["tags"],
            "structured_output": copy.deepcopy(session["handoff"]),
        }

    def gh(self, method, path, **kwargs):
        prefix = f"repos/{REPOSITORY}/"
        assert path.startswith(prefix), f"Out-of-scope request: {path}"
        resource = path.removeprefix(prefix)
        params = kwargs.get("params", {})
        body = kwargs.get("json", {})
        if method == "GET":
            if resource == f"commits/{BRANCH}":
                return {"sha": BASE}
            if resource == "issues":
                return list(self.issues.values())
            if resource.startswith("issues/"):
                return self.issues[int(resource.split("/")[-1])]
            if resource == "pulls":
                return [
                    copy.deepcopy(pr)
                    for pr in self.pulls.values()
                    if not params.get("head")
                    or params["head"].split(":", 1)[1] == pr["head"]["ref"]
                ]
            if resource.startswith("git/ref/heads/"):
                branch = resource.removeprefix("git/ref/heads/")
                if branch not in self.refs:
                    raise ProviderError("Simulated absent ref", 404)
                return {"object": {"sha": self.refs[branch]}}
            if resource.endswith("/check-runs"):
                sha = resource.split("/")[1]
                return {
                    "check_runs": [
                        {
                            "name": "synthetic-ci",
                            "status": "completed",
                            "conclusion": "failure" if sha == INTEGRATED else "success",
                            "html_url": "https://github.com/Simulated/superset/actions/runs/1",
                        }
                    ]
                }
            if resource.endswith("/status"):
                return {"statuses": []}
            if resource.endswith("required_status_checks"):
                return {"contexts": ["synthetic-ci"]}
            if resource.startswith("rules/branches/"):
                return []
        elif method == "POST":
            if resource == "issues":
                self.remote_effects["issue"] += 1
                self.issues[1] = {
                    **body,
                    "number": 1,
                    "state": "open",
                    "user": {"login": "Simulated"},
                    "labels": [{"name": label} for label in body["labels"]],
                    "html_url": f"https://github.com/{REPOSITORY}/issues/1",
                }
                return copy.deepcopy(self.issues[1])
            if resource == "git/refs":
                self.remote_effects["integration_ref"] += 1
                self.refs[body["ref"].removeprefix("refs/heads/")] = body["sha"]
                return {}
            if resource == "merges":
                assert body["base"].startswith("cognition/integration/")
                assert body["head"] == IMPLEMENTED
                self.remote_effects["integration_merge"] += 1
                self.refs[body["base"]] = INTEGRATED
                return {"sha": INTEGRATED}
            if resource == "pulls":
                assert body["base"] == BRANCH and body["draft"] is True
                self.remote_effects["integration_pr"] += 1
                self.pulls[3] = self.pull(3, self.refs[body["head"]], body["head"], draft=True)
                self.pulls[3]["title"] = body["title"]
                return copy.deepcopy(self.pulls[3])
        raise AssertionError(f"Unexpected simulated provider request: {method} {resource}")

    def comment(self, number, body, repository=None):
        assert repository == REPOSITORY
        self.comments.append((number, body))
        return {"id": len(self.comments)}

    def confirm_publication(self, payload, receipt):
        assert self.comments[receipt["id"] - 1] == (payload["number"], payload["body"])
        return f"https://github.com/{REPOSITORY}/issues/{payload['number']}#issuecomment-{receipt['id']}"

    def mark_ready(self, number, expected_sha):
        assert number == 3 and self.pulls[number]["head"]["sha"] == expected_sha == REMEDIATED
        self.remote_effects["ready_for_review"] += 1
        self.pulls[number]["draft"] = False
        return {"number": number, "sha": expected_sha}


def test_simulated_discovery_to_remediation_to_verified_publication_survives_restart(
    tmp_path, monkeypatch
):
    """All transitions use the real worker/store; only external providers are simulated."""
    now = [1_800_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    settings = Settings(
        database=str(tmp_path / "simulated-workflow.db"),
        repo=REPOSITORY,
        branch=BRANCH,
        org="simulated-organization",
        allowed_actor="Simulated",
        enabled=True,
        devin_key="synthetic-not-a-key",
        github_token="synthetic-not-a-token",
        learning_enabled=False,
        dependabot_enabled=False,
        batch_seconds=0,
        max_sessions=8,
        max_acu=2,
        scan_interval=86400,
        poll_seconds=1,
    )
    remote = SimulatedProviders()
    engine = Engine(settings, Store(settings.database), remote)
    restarted = False
    leased_remediation = None
    for _ in range(35):
        now[0] += 61
        cycle(engine)
        assert engine.store.recall("worker_status")["failures"] == []
        jobs = engine.store.operational_jobs()
        running = next(
            (j for j in jobs if j["kind"] == "remediation" and j["state"] == "running"), None
        )
        if running:
            leased_remediation = copy.deepcopy(running)
        prepared = next(
            (j for j in jobs if j["kind"] == "remediation" and j["state"] == "prepared"), None
        )
        if prepared and not restarted:
            assert leased_remediation is not None
            # Simulate process restart after committed handoff but before report delivery.
            engine.store.database.engine.dispose()
            engine = Engine(settings, Store(settings.database), remote)
            engine.poll(leased_remediation)  # Duplicate completed provider observation.
            restarted = True
        if remote.remote_effects["ready_for_review"] and all(
            p["state"] in {"sent", "stale"} for p in engine.store.all_publications()
        ):
            break
    else:
        raise AssertionError([(j["kind"], j["state"], j["error"]) for j in engine.store.jobs()])

    assert restarted
    jobs = engine.store.operational_jobs()
    scan = next(j for j in jobs if j["kind"] == "scan")
    repair = next(j for j in jobs if j["kind"] == "repair")
    integration = next(j for j in jobs if j["kind"] == "integration")
    remediation = next(j for j in jobs if j["kind"] == "remediation")
    validations = [j for j in jobs if j["kind"] == "validation"]
    assert len(validations) == 2
    failed = next(j for j in validations if j["candidate_sha"] == INTEGRATED)
    ready = next(j for j in validations if j["candidate_sha"] == REMEDIATED)
    assert scan["state"] == "completed" and repair["parent_id"] == scan["id"]
    assert integration["payload"]["members"][0]["job_id"] == repair["id"]
    assert failed["state"] == "stale" and failed["result"]["gate"] == "validation_failed"
    assert failed["result"]["provenance"] == "github_ci_preflight" and failed["session_id"] is None
    assert remediation["parent_id"] == failed["id"] and ready["parent_id"] == remediation["id"]
    assert ready["state"] == "review_ready" and ready["result"]["ci"]["state"] == "success"
    assert ready["session_id"] not in {repair["session_id"], remediation["session_id"]}
    assert {a["kind"] for a in ready["result"]["artifacts"]} == {
        "screenshot",
        "video",
        "logs",
        "tests",
        "api",
        "coverage",
    }
    assert remote.pulls[3]["draft"] is False
    assert remote.remote_effects == Counter(
        {
            "devin_session:scan": 1,
            "issue": 1,
            "devin_session:repair": 1,
            "devin_implementation_pr": 1,
            "integration_ref": 1,
            "integration_merge": 1,
            "integration_pr": 1,
            "devin_session:remediation": 1,
            "devin_remediation_push": 1,
            "devin_session:validation": 1,
            "ready_for_review": 1,
        }
    )
    markers = [body.splitlines()[0] for _, body in remote.comments]
    assert len(markers) == len(set(markers))
    final_report = next(
        body
        for number, body in remote.comments
        if number == 3 and "release validation — review ready" in body
    )
    assert REMEDIATED in final_report and "![Superset running" in final_report
    assert (
        "video:" in final_report
        and "curl -X POST" in final_report
        and "Line coverage:" in final_report
    )
    assert "configured GitHub integration publishes" in final_report
    for _ in range(3):
        now[0] += 61
        cycle(engine)
    assert len(remote.sessions) == 4 and remote.remote_effects["ready_for_review"] == 1
    assert len(remote.comments) == len(markers)
