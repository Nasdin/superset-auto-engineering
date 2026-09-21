"""Auditable PR title/label rules shared by Python and generated Postgres SQL.

Explicit change intent wins over incidental dependency words or broad labels.
A GitHub bot author is a separate dimension and takes precedence only in charts.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CLASSIFICATION_VERSION = "2026-09-21-v2"
WorkKind = Literal[
    "",
    "fix",
    "feature",
    "dependency",
    "docs",
    "refactor",
    "test",
    "build",
    "performance",
    "release",
    "revert",
    "maintenance",
    "unclassified",
    "bot",
]
CATEGORY_LABELS = {
    "fix": "Fixes",
    "feature": "Features",
    "dependency": "Dependencies",
    "docs": "Documentation",
    "refactor": "Refactoring",
    "test": "Tests",
    "build": "Build & CI",
    "performance": "Performance",
    "release": "Releases",
    "revert": "Reverts",
    "maintenance": "Maintenance",
    "unclassified": "Needs classification",
}
SEGMENTS = ("Fixes", "Features", "Bots", *list(CATEGORY_LABELS.values())[2:])


@dataclass(frozen=True)
class Rule:
    kind: str
    reason: str
    title: str = ""
    label: str = ""


def prefix(types):
    # Common regex subset supported by Python and PostgreSQL. Optional [scope]
    # prefixes occur in older Superset titles, before conventional commits.
    return rf"^(\[[^]]+\][ ]*)?({types})([^a-z0-9_]|$)"


RULES = (
    Rule("revert", "Revert or rollback title", prefix("revert|rollback")),
    Rule("fix", "Fix title", prefix("fix|bugfix|hotfix")),
    Rule("feature", "Feature title", prefix("feat|feature")),
    Rule("docs", "Documentation title", prefix("docs?|documentation")),
    Rule("refactor", "Refactoring title", prefix("refactor")),
    Rule("test", "Test title", prefix("tests?|testing")),
    Rule("performance", "Performance title", prefix("perf|performance")),
    Rule("release", "Release title", prefix("release") + r"|^helm chart release([^a-z0-9_]|$)"),
    *(
        Rule(kind, "Explicit " + CATEGORY_LABELS[kind].lower() + " scope", rf"^chore\(({scope})\)")
        for kind, scope in (
            ("docs", "docs?|documentation"),
            ("build", "ci|build"),
            ("test", "tests?|testing"),
            ("performance", "perf|performance"),
            ("refactor", "refactor"),
            ("release", "release"),
        )
    ),
    Rule(
        "dependency",
        "Dependency update title",
        r"^(chore|build)\(deps[^)]*\)|^(chore:[ ]*)?(bump|upgrade|downgrade|pin)[ ]",
    ),
    Rule("build", "Build or CI title", prefix("build|ci")),
    # Narrow dependency labels apply after explicit intent, before generic chores.
    Rule("dependency", "Dependency label", label=r"^(dependencies(:.*)?|\.dependency|dependabot)$"),
    Rule("maintenance", "Maintenance or styling title", prefix("chore|style|cleanup")),
    Rule("fix", "Bug or fix label", label=r"^(#?bug|fix|bugfix|type:bug|type: bug)$"),
    Rule(
        "feature",
        "Feature or enhancement label",
        label=r"^(#?feature|enhancement|type:feature|type: feature)$",
    ),
    Rule("docs", "Documentation label", label=r"^(#?docs?|documentation|type:documentation)$"),
    Rule("refactor", "Refactoring label", label=r"^(refactor|refactoring)$"),
    Rule("test", "Test label", label=r"^(test|tests|testing)$"),
    Rule("build", "Build or CI label", label=r"^(build|ci|ci/cd)$"),
    Rule("performance", "Performance label", label=r"^(perf|performance)$"),
    Rule("release", "Release label", label=r"^(release|releases)$"),
    Rule("maintenance", "Maintenance label", label=r"^(maintenance|chore|cleanup)$"),
    Rule(
        "dependency",
        "Dependency update wording",
        r"(^|[^a-z0-9_])(bump|upgrade|downgrade|pin)[ ]|^(deps|dependencies|dependency)([^a-z0-9_]|$)",
    ),
    Rule(
        "maintenance",
        "Community metadata update",
        r"(add|adding).*(to inthewild|to supersetbot metadata)",
    ),
)


# Reviewed exceptions are repository-scoped and cite their public evidence.
# Unlike an unknown-title catch-all, each entry has an inspectable rationale.
REVIEWED = {
    "https://github.com/apache/superset/pull/39640": (
        "feature",
        "Reviewed PR body and diff: new semantic-layer access permissions",
    ),
}


def classify(pr):
    if pr.get("url") in REVIEWED:
        return REVIEWED[pr["url"]]
    title = (pr.get("title") or "").strip().lower()
    labels = [(label or "").lower() for label in pr.get("labels", [])]
    for rule in RULES:
        if (rule.title and re.search(rule.title, title)) or (
            rule.label and any(re.search(rule.label, label) for label in labels)
        ):
            return rule.kind, rule.reason
    if (pr.get("author") or "").lower() == "dependabot[bot]":
        return "dependency", "Dependabot author"
    return "unclassified", "No reliable type signal in title or labels"


def category(pr):
    return classify(pr)[0]


def sql_case(reason=False):
    """Generate the exact ordered rule table for the checked-in reporting view."""

    def literal(value):
        return "'" + value.replace("'", "''") + "'"

    lines = ["CASE"]
    for url, (kind, explanation) in REVIEWED.items():
        lines.append(f" WHEN url={literal(url)} THEN {literal(explanation if reason else kind)}")
    for rule in RULES:
        condition = (
            f"lower(btrim(title)) ~ {literal(rule.title)}"
            if rule.title
            else "EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE "
            f"lower(l) ~ {literal(rule.label)})"
        )
        lines.append(f" WHEN {condition} THEN {literal(rule.reason if reason else rule.kind)}")
    lines.append(
        " WHEN lower(author)='dependabot[bot]' THEN "
        + literal("Dependabot author" if reason else "dependency")
    )
    lines.append(
        " ELSE "
        + literal("No reliable type signal in title or labels" if reason else "unclassified")
        + " END"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    path = Path(__file__).with_name("reporting.sql")
    source = path.read_text()
    for field, expression in (("category", sql_case()), ("classification_reason", sql_case(True))):
        start, stop = f"-- BEGIN GENERATED {field}\n", f"-- END GENERATED {field}"
        before, tail = source.split(start)
        _, after = tail.split(stop)
        comma = "," if field == "category" else ""
        source = before + start + expression + f" AS {field}{comma}\n" + stop + after
    path.write_text(source)
