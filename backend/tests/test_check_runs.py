from copy import deepcopy

import pytest
from app.automation.check_runs import current_checks
from app.automation.config import Settings
from app.automation.providers import ProviderError

SHA = "a" * 40


def check(run_id, conclusion):
    return {
        "name": "check-hold-label",
        "status": "completed" if conclusion else "queued",
        "conclusion": conclusion,
        "app": {"slug": "github-actions"},
        "check_suite": {"id": run_id * 10},
        "html_url": f"https://github.com/Nasdin/superset/actions/runs/{run_id}/job/{run_id * 100}",
    }


class Provider:
    def __init__(self):
        self.runs = {
            i: {
                "id": i,
                "check_suite_id": i * 10,
                "head_sha": SHA,
                "workflow_id": 42,
                "run_number": i,
                "run_attempt": 1,
                "event": "pull_request",
                "head_branch": "human-demo",
            }
            for i in (1, 2)
        }
        self.calls = []

    def gh(self, method, path):
        self.calls.append(path)
        return deepcopy(self.runs[int(path.rsplit("/", 1)[1])])


@pytest.mark.parametrize("conclusion", [None, "success", "failure", "cancelled"])
def test_only_confirmed_newer_workflow_run_supersedes_old_check(conclusion):
    older, newer = check(1, "cancelled"), check(2, conclusion)
    for rows in ([older, newer], [newer, older]):
        active, superseded = current_checks(Settings(), Provider(), SHA, rows)
        assert active == [newer]
        assert superseded == [older]


@pytest.mark.parametrize(
    "field,value", [("workflow_id", 99), ("event", "push"), ("head_branch", "another")]
)
def test_same_name_does_not_hide_an_unrelated_workflow_failure(field, value):
    p = Provider()
    p.runs[2][field] = value
    rows = [check(1, "failure"), check(2, "success")]
    assert current_checks(Settings(), p, SHA, rows) == (rows, [])


@pytest.mark.parametrize(
    "field,value", [("head_sha", "b" * 40), ("id", 3), ("check_suite_id", 1), ("workflow_id", None)]
)
def test_incomplete_workflow_identity_never_suppresses_failure(field, value):
    p = Provider()
    p.runs[2][field] = value
    with pytest.raises(ProviderError, match="identity is incomplete"):
        current_checks(Settings(), p, SHA, [check(1, "failure"), check(2, "success")])


def test_foreign_check_urls_are_not_followed_or_removed():
    p = Provider()
    rows = [check(1, "failure"), check(2, "success")]
    for row in rows:
        row["html_url"] = row["html_url"].replace("Nasdin/superset", "other/repo")
    assert current_checks(Settings(), p, SHA, rows) == (rows, [])
    assert p.calls == []


def test_missing_suite_on_both_sides_does_not_establish_identity():
    p = Provider()
    p.runs[2].pop("check_suite_id")
    rows = [check(1, "failure"), check(2, "success")]
    rows[1].pop("check_suite")
    with pytest.raises(ProviderError, match="identity is incomplete"):
        current_checks(Settings(), p, SHA, rows)
