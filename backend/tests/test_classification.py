"""Semantic precedence, auditable exceptions and Python/SQL rule drift."""

from pathlib import Path

import pytest
from app.analytics.classification import CATEGORY_LABELS, RULES, classify, sql_case
from app.analytics.impact import segment
from test_analytics import record

CASES = [
    ("fix(native-filters): keep cascade dependency gate", ["dependencies:npm"], "fix"),
    ("feat(dashboard): iframe", ["dependencies:npm"], "feature"),
    ("fix: revert an invalid dependency", [], "fix"),
    ('Revert "feat: chart"', ["feature"], "revert"),
    ("docs: examples", ["dependencies:npm"], "docs"),
    ("chore(deps): bump library", ["bug"], "dependency"),
    ("build(deps-dev): update types", [], "dependency"),
    ("chore(ci): update actions", ["dependencies:npm"], "build"),
    ("chore(docs): rename plugin", ["dependencies:npm"], "docs"),
    ("chore(test): clean setup", [], "test"),
    ("test: dependency compatibility", [], "test"),
    ("refactor: simplify SQL", [], "refactor"),
    ("perf: reduce reads", [], "performance"),
    ("ci: update workflow", [], "build"),
    ("build: compile assets", [], "build"),
    ("Helm chart release for helm-publish-abc", [], "release"),
    ("style: align imports", [], "maintenance"),
    ("chore: update notices", [], "maintenance"),
    ("[docker] fix, Dockerfile for frontend builds", [], "fix"),
    ("Repair query behavior", ["#bug"], "fix"),
    ("other: resolve frontend dep vulns", ["doc", "dependencies:npm"], "dependency"),
    ("other: Add TechAuditBI to supersetbot metadata.js", [], "maintenance"),
    (" Sl permissions ", ["authentication:RBAC"], "unclassified"),
    ("featureless title", [], "unclassified"),
]


@pytest.mark.parametrize("title,labels,expected", CASES)
def test_explicit_intent_precedes_incidental_words_and_broad_labels(title, labels, expected):
    pr = record(title=title, labels=labels)
    kind, reason = classify(pr)
    assert kind == expected
    assert reason
    assert segment(pr) == CATEGORY_LABELS[kind]
    assert segment({**pr, "author_type": "Bot"}) == "Bots"
    assert segment({**pr, "labels": [*labels, "🏷️ bot"]}) == CATEGORY_LABELS[kind]


def test_reviewed_exception_is_bound_to_exact_repository_and_pr():
    reviewed = record(39640, title="Sl permissions", labels=[])
    assert classify(reviewed) == (
        "feature",
        "Reviewed PR body and diff: new semantic-layer access permissions",
    )
    reviewed["url"] = "https://github.com/Nasdin/superset/pull/39640"
    assert classify(reviewed)[0] == "unclassified"


def test_postgres_rules_are_generated_from_the_same_ordered_rule_table():
    sql = (Path(__file__).parents[1] / "app/analytics/reporting.sql").read_text()
    assert sql_case() + " AS category," in sql
    assert sql_case(True) + " AS classification_reason\n" in sql
    assert len({rule.kind for rule in RULES}) == len(CATEGORY_LABELS) - 1
