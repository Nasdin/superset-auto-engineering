"""Current-revision GitHub checks, separate from Devin's runtime evidence."""

from urllib.parse import quote

from .providers import ProviderError


def current_pr(settings, providers, number, sha):
    pr = providers.pr(number)
    if (
        pr.get("state") != "open"
        or pr.get("base", {}).get("ref") != settings.branch
        or (pr.get("base", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or (pr.get("head", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or pr.get("head", {}).get("sha") != sha
        or not pr.get("head", {}).get("ref")
        or pr["head"]["ref"] == settings.branch
    ):
        raise ValueError("PR is no longer open at the authorized fork branch and revision")
    return pr


def ci_status(settings, providers, number, sha):
    """Inspect every reported check; absence is explicit, never fabricated passing CI."""
    current_pr(settings, providers, number, sha)
    checks = []
    page = 1
    while True:
        result = providers.gh(
            "GET",
            f"repos/{settings.repo}/commits/{sha}/check-runs",
            params={"per_page": 100, "page": page, "filter": "latest"},
        )
        if not isinstance(result, dict) or not isinstance(result.get("check_runs"), list):
            raise ProviderError(
                "GitHub checks response is incomplete", category="invalid_result", retryable=False
            )
        rows = result["check_runs"]
        checks.extend(
            {
                "name": c["name"],
                "status": c["status"],
                "conclusion": c.get("conclusion"),
                "url": c.get("html_url", ""),
            }
            for c in rows
        )
        if len(rows) < 100:
            break
        page += 1
        if page > 20:
            raise ProviderError("CI check pagination exceeds inspection limit")
    # Combined status lists the most recent status for each context; paginate it too.
    page = 1
    while True:
        result = providers.gh(
            "GET",
            f"repos/{settings.repo}/commits/{sha}/status",
            params={"per_page": 100, "page": page},
        )
        if not isinstance(result, dict) or not isinstance(result.get("statuses"), list):
            raise ProviderError(
                "GitHub status response is incomplete", category="invalid_result", retryable=False
            )
        rows = result["statuses"]
        checks.extend(
            {
                "name": c["context"],
                "status": "completed" if c["state"] != "pending" else "pending",
                "conclusion": c["state"],
                "url": c.get("target_url") or "",
            }
            for c in rows
        )
        if len(rows) < 100:
            break
        page += 1
        if page > 20:
            raise ProviderError("CI status pagination exceeds inspection limit")
    required = set()
    branch = quote(settings.branch, safe="")
    for path in (
        f"repos/{settings.repo}/branches/{branch}/protection/required_status_checks",
        f"repos/{settings.repo}/rules/branches/{branch}",
    ):
        try:
            rules = providers.gh("GET", path)
        except ProviderError as error:
            if error.status == 404:
                continue
            raise
        if isinstance(rules, dict):
            required.update(rules.get("contexts", []))
            required.update(c["context"] for c in rules.get("checks", []))
        elif isinstance(rules, list):
            for rule in rules:
                if rule.get("type") == "required_status_checks":
                    required.update(
                        c["context"]
                        for c in rule.get("parameters", {}).get("required_status_checks", [])
                    )
    reported = {c["name"] for c in checks}
    checks.extend(
        {"name": name, "status": "pending", "conclusion": None, "url": ""}
        for name in sorted(required - reported)
    )
    failed = any(
        c["status"] == "completed" and c["conclusion"] not in {"success", "neutral", "skipped"}
        for c in checks
    )
    pending = any(c["status"] != "completed" for c in checks)
    return {
        "sha": sha,
        "state": "failure" if failed else "pending" if pending else "success",
        "checks": checks,
        "configured": bool(checks),
    }
