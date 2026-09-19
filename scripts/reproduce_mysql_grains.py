"""Behavioral qualification against real MySQL; exit 1 when baseline is defective."""

import argparse
import ast
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import sqlglot

p = argparse.ArgumentParser()
p.add_argument("--repo", required=True)
p.add_argument("--ref", required=True)
p.add_argument("--container", default="cognition-mysql-repro")
p.add_argument("--output", default="evidence/mysql-baseline.json")
a = p.parse_args()
sha = subprocess.check_output(
    ["git", "-C", a.repo, "rev-parse", a.ref], text=True
).strip()
source = subprocess.check_output(
    ["git", "-C", a.repo, "show", f"{sha}:superset/db_engine_specs/mysql.py"], text=True
)
expressions = {}
for node in ast.walk(ast.parse(source)):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "_time_grain_expressions"
        for t in node.targets
    ):
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Attribute) and key.attr in [
                "SECOND",
                "MINUTE",
                "HOUR",
            ]:
                expressions[key.attr] = ast.literal_eval(value)
rows = []
for value in ["2026-09-18 00:00:00", "2026-09-18 08:15:30", "2026-09-18 23:59:59"]:
    dt = datetime.fromisoformat(value)
    for grain, expression in expressions.items():
        expected = dt.replace(
            second=0 if grain in ["MINUTE", "HOUR"] else dt.second,
            minute=0 if grain == "HOUR" else dt.minute,
        ).isoformat(" ")
        original = (
            "SELECT "
            + expression.format(col=f"CAST('{value}' AS DATETIME)")
            + " AS bucket"
        )
        rewritten = sqlglot.parse_one(original, read="mysql").sql(dialect="mysql")
        completed = subprocess.run(
            [
                "docker",
                "exec",
                a.container,
                "mysql",
                "-uroot",
                "--batch",
                "--skip-column-names",
                "-e",
                rewritten,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        actual = completed.stdout.strip()
        rows.append(
            dict(
                grain=grain,
                input=value,
                expected=expected,
                actual=actual,
                passed=actual == expected,
                original_sql=original,
                rewritten_sql=rewritten,
            )
        )
result = {
    "baseline_sha": sha,
    "sqlglot_version": sqlglot.__version__,
    "mysql_version": subprocess.check_output(
        [
            "docker",
            "exec",
            a.container,
            "mysql",
            "-uroot",
            "--batch",
            "--skip-column-names",
            "-e",
            "SELECT VERSION()",
        ],
        text=True,
    ).strip(),
    "passed": all(r["passed"] for r in rows),
    "checks": rows,
}
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(0 if result["passed"] else 1)
