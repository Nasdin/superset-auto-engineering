"""Resolve superseded Actions checks without conflating unrelated workflows."""

import re
from collections import Counter

from .providers import ProviderError


def current_checks(settings, providers, sha, checks):
    """GitHub's latest filter applies per suite, so same-SHA suites can overlap."""
    duplicates = {name for name, count in Counter(c["name"] for c in checks).items() if count > 1}
    runs, identities = {}, {}
    pattern = rf"https://github\.com/{re.escape(settings.repo)}/actions/runs/(\d+)/job/\d+"
    for index, check in enumerate(checks):
        if (
            check["name"] not in duplicates
            or (check.get("app") or {}).get("slug") != "github-actions"
        ):
            continue
        match = re.fullmatch(pattern, check.get("html_url", ""))
        if not match:
            continue
        run_id = int(match[1])
        if run_id not in runs:
            if len(runs) >= 100:
                raise ProviderError("CI workflow identity lookup exceeds inspection limit")
            runs[run_id] = providers.gh("GET", f"repos/{settings.repo}/actions/runs/{run_id}")
        run = runs[run_id]
        if not (
            isinstance(run, dict)
            and run.get("id") == run_id
            and run.get("head_sha") == sha
            and run.get("check_suite_id") == (check.get("check_suite") or {}).get("id")
            and all(
                type(run.get(k)) is int and run[k] > 0
                for k in ("check_suite_id", "workflow_id", "run_number", "run_attempt")
            )
            and isinstance(run.get("event"), str)
            and isinstance(run.get("head_branch"), str)
        ):
            raise ProviderError(
                "GitHub workflow identity is incomplete", category="invalid_result", retryable=False
            )
        identity = (run["workflow_id"], run["event"], run["head_branch"], check["name"])
        identities[index] = (identity, (run["run_number"], run["run_attempt"]))
    newest = {}
    for identity, rank in identities.values():
        newest[identity] = max(newest.get(identity, rank), rank)
    active, superseded = [], []
    for index, check in enumerate(checks):
        entry = identities.get(index)
        (superseded if entry and entry[1] < newest[entry[0]] else active).append(check)
    return active, superseded
