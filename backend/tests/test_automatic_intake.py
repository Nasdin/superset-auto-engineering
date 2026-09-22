"""Automatic intake remains scoped and feeds the existing durable pipelines."""

from dataclasses import replace

import pytest
from app.automation.config import Settings
from app.automation.engine import Engine
from app.automation.inbox import Inbox
from app.automation.pr_validation import PullRequestValidationService, eligible_validation
from app.automation.store import Store
from test_pr_validation import PullRequestProvider


def test_automatic_owner_pr_needs_no_label_and_duplicate_events_coalesce(tmp_path):
    settings = replace(Settings(), automatic_intake=True, database=str(tmp_path / "jobs.db"))
    store = Store(settings.database)
    provider = PullRequestProvider(settings)
    provider.document["labels"] = []
    engine = Engine(settings, store, provider)
    inbox = Inbox(engine)
    payload = {"event": "pull_request", "number": 8, "sha": provider.document["head"]["sha"]}
    for delivery in ["one", "two"]:
        inbox.accept(delivery, payload)
        assert inbox.tick()["state"] == "completed"
    assert len(store.jobs()) == 1
    assert store.jobs()[0]["kind"] == "validation"
    assert (
        PullRequestValidationService(settings, store, provider).accept(8, "poll")["id"]
        == store.jobs()[0]["id"]
    )


@pytest.mark.parametrize(
    "change", ["disabled", "foreign_author", "foreign_head", "wrong_base", "draft"]
)
def test_automatic_pr_does_not_bypass_scope(tmp_path, change):
    settings = replace(Settings(), automatic_intake=True)
    pr = PullRequestProvider(settings).document
    pr["labels"] = []
    if change == "disabled":
        settings = replace(settings, automatic_intake=False)
    elif change == "foreign_author":
        pr["user"]["login"] = "stranger"
    elif change == "foreign_head":
        pr["head"]["repo"]["full_name"] = "stranger/superset"
    elif change == "wrong_base":
        pr["base"]["ref"] = "unrelated"
    else:
        pr["draft"] = True
    with pytest.raises(ValueError):
        eligible_validation(settings, pr)


def test_automatic_issue_poll_and_webhook_share_one_durable_job(tmp_path):
    settings = replace(Settings(), automatic_intake=True, database=str(tmp_path / "jobs.db"))
    issue = {
        "number": 7,
        "state": "open",
        "labels": [],
        "user": {"login": settings.allowed_actor},
        "title": "Regression",
        "html_url": "https://github.com/Nasdin/superset/issues/7",
    }

    class Provider:
        def gh(self, method, path, **kwargs):
            if path.endswith("/issues"):
                assert "labels" not in kwargs["params"]
                return [issue]
            if "/issues/" in path:
                return issue
            return {"sha": "a" * 40}

    store = Store(settings.database)
    engine = Engine(settings, store, Provider())
    engine.poll_issues()
    engine.accept_webhook(7, "delivery")
    assert len(store.jobs()) == 1
    assert store.jobs()[0]["kind"] == "repair"
    issue["user"]["login"] = "stranger"
    with pytest.raises(ValueError, match="author"):
        engine.accept_issue(8, "poll")


def test_env_defaults_require_labels():
    assert not Settings.from_env({}).automatic_intake
    assert Settings.from_env({"AUTOMATIC_INTAKE": "true"}).automatic_intake


def test_rollout_boundary_does_not_replay_older_isolated_work():
    from app.automation.intake_policy import automatic_intake

    settings = Settings(automatic_intake=True, automatic_intake_since="2026-09-22T00:00:00Z")
    assert not automatic_intake(settings, {"created_at": "2026-09-21T23:59:59Z"})
    assert not automatic_intake(settings, {})
    assert automatic_intake(settings, {"created_at": "2026-09-22T00:00:00Z"})
    with pytest.raises(ValueError):
        Settings.from_env({"AUTOMATIC_INTAKE_SINCE": "2026-09-22"})
