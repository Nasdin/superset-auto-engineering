"""Reproduce public EDA from the committed snapshot. --fetch-sample refreshes 12 PR details."""

import argparse
import csv
import json
import random
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.analytics.metrics import category, cohort, summarize  # noqa: E402

OUT = ROOT / "docs" / "analysis"
parser = argparse.ArgumentParser()
parser.add_argument("--fetch-sample", action="store_true")
args = parser.parse_args()
OUT.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(ROOT / "backend/app/seeds/github-history.sqlite3") as db:
    pulls = [
        json.loads(row[0])
        for row in db.execute("SELECT data FROM pull_requests WHERE repository='apache/superset'")
    ]
    coverage = json.loads(
        db.execute("SELECT data FROM sync_status WHERE repository='apache/superset'").fetchone()[0]
    )
commits = json.loads((OUT / "commits.json").read_text())
for item in commits["commits"]:
    item["category"] = category({**item, "labels": []})
    item["dependabot"] = item["author"].lower() == "dependabot[bot]"
(OUT / "commits.json").write_text(json.dumps(commits, indent=2) + "\n")
months = []
for end, days in [
    (date(2026, 6, 30), 30),
    (date(2026, 7, 31), 31),
    (date(2026, 8, 31), 31),
    (date(2026, 9, 19), 19),
]:
    rows = cohort(pulls, end, days)
    months.append(
        {
            **summarize(pulls, end, days),
            "partial_month": end.month == 9,
            "categories": dict(Counter(category(pr) for pr in rows)),
            "dependabot_authored": sum(pr["author"] == "dependabot[bot]" for pr in rows),
        }
    )
august = cohort(pulls, date(2026, 8, 31), 31)
groups = {
    "dependabot": [pr for pr in august if pr["author"] == "dependabot[bot]"],
    "fix": [pr for pr in august if category(pr) == "fix"],
    "feature": [pr for pr in august if category(pr) == "feature"],
    "other": [pr for pr in august if category(pr) == "other"],
}
if args.fetch_sample:
    sample = []
    for group, rows in groups.items():
        for pr in random.Random(42).sample(
            sorted(rows, key=lambda row: row["number"]), min(3, len(rows))
        ):
            retained = json.loads(
                subprocess.check_output(
                    [
                        "gh",
                        "api",
                        f"repos/apache/superset/pulls/{pr['number']}/commits?per_page=100",
                    ],
                    text=True,
                )
            )
            details = [
                {
                    "sha": c["sha"],
                    "url": c["html_url"],
                    "title": c["commit"]["message"].splitlines()[0],
                    "committed_at": c["commit"]["committer"]["date"],
                    "merge": len(c["parents"]) > 1,
                }
                for c in retained
            ]
            sample.append(
                {
                    "stratum": group,
                    "number": pr["number"],
                    "title": pr["title"],
                    "url": pr["url"],
                    "created_at": pr["created_at"],
                    "merged_at": pr["merged_at"],
                    "commits": details,
                    "possibly_truncated": len(details) == 100,
                }
            )
    (OUT / "pr-commit-sample.json").write_text(
        json.dumps(
            {
                "seed": 42,
                "method": "Three PRs per stratum from August merge cohort; sorted by PR number then random.Random(42).sample independently per stratum. Up to first 100 retained commits per PR. Strata deliberately balanced, not population representative.",
                "pull_requests": sample,
            },
            indent=2,
        )
        + "\n"
    )
sample_doc = json.loads((OUT / "pr-commit-sample.json").read_text())
for pr in sample_doc["pull_requests"]:
    pr["retained_commits"] = len(pr["commits"])
    pr["committed_after_open"] = sum(c["committed_at"] > pr["created_at"] for c in pr["commits"])
    pr["merge_commits"] = sum(c["merge"] for c in pr["commits"])
(OUT / "pr-commit-sample.json").write_text(json.dumps(sample_doc, indent=2) + "\n")
summary = {
    "repository": "apache/superset",
    "snapshot": coverage,
    "rules": "Retrospective signals, precedence: revert/rollback title; exact Dependabot author or dependency title/labels; fix/bug title/labels; feat/feature title or feature/enhancement label; other. Dependabot provenance is also retained separately. Commits have no PR labels.",
    "months": months,
    "commit_sample": {
        "n": len(commits["commits"]),
        "head_sha": commits["head_sha"],
        "categories": dict(Counter(c["category"] for c in commits["commits"])),
        "dependabot_authored": sum(c["dependabot"] for c in commits["commits"]),
        "merge_commits": sum(len(c["parents"]) > 1 for c in commits["commits"]),
    },
    "comparison": {
        kind: {
            "recent": summarize(
                [p for p in pulls if kind == "all" or category(p) == kind], date(2026, 9, 19), 30
            ),
            "six_months_earlier": summarize(
                [p for p in pulls if kind == "all" or category(p) == kind], date(2026, 3, 19), 30
            ),
        }
        for kind in ["all", "dependency", "fix", "feature"]
    },
    "pr_sample": [
        {k: v for k, v in p.items() if k != "commits"} for p in sample_doc["pull_requests"]
    ],
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
with (OUT / "commit-classification.csv").open("w") as f:
    writer = csv.DictWriter(
        f, fieldnames=["sha", "date", "author", "dependabot", "category", "title", "url"]
    )
    writer.writeheader()
    writer.writerows({k: c[k] for k in writer.fieldnames} for c in commits["commits"])
with (OUT / "august-pr-classification.csv").open("w") as f:
    fields = [
        "number",
        "author",
        "dependabot",
        "category",
        "title",
        "created_at",
        "merged_at",
        "url",
    ]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(
        {
            k: {**p, "category": category(p), "dependabot": p["author"] == "dependabot[bot]"}[k]
            for k in fields
        }
        for p in sorted(august, key=lambda p: p["number"])
    )
print(
    json.dumps(
        {
            "months": months,
            "commit_sample": summary["commit_sample"],
            "comparison": summary["comparison"],
        },
        indent=2,
    )
)
