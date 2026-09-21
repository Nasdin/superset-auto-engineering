"""Reviewed automation recipes. Schedules and execution live in our durable ledger."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    description: str
    focus: str
    interval: int = 86400
    kind: str = "scan"
    category: str = "Engineering"


RECIPES = {
    recipe.id: recipe
    for recipe in (
        Recipe(
            "discovery",
            "Autonomous correctness scan",
            "Find one reproducible regression and carry it through repair and independent validation.",
            "Find at most ONE bounded data-correctness or regression defect with a runnable failing reproduction. Focus on database engine SQL generation and query behavior.",
        ),
        Recipe(
            "dependency_vulnerabilities",
            "Dependency Vulnerability Scanner",
            "Check dependencies against advisories, then prepare a scoped fix with regression evidence.",
            "Inspect pinned direct and transitive dependencies using advisory databases and the repository's scanners. Cite advisory IDs and affected/fixed versions; verify applicability. Choose at most one actionable vulnerability with a safe local reproduction or reproducible scanner result. Respect SECURITY.md disclosure policy; never publish a new embargoed vulnerability.",
            category="Security",
        ),
        Recipe(
            "secret_scan",
            "Secret Scanner",
            "Find hardcoded credentials and prepare one tested environment-reference fix.",
            "Run a secret scanner with full redaction against the checkout. Distinguish fixtures from real hardcoded credentials. If a confirmed hardcoded credential exists, replace at most one use with an environment reference, update configuration instructions and add regression tests without copying the credential into a test. Never report secret values, snippets, fingerprints or raw scanner logs. Do not test, rotate or revoke credentials. Report only rule IDs and locations; credential rotation remains an operator action.",
            kind="maintenance",
            category="Security",
        ),
        Recipe(
            "code_patterns",
            "Code Pattern Enforcer",
            "Use this fork's documented conventions to propose one tested alignment fix.",
            "Use this fork's AGENTS.md, CONTRIBUTING instructions, lint configuration and nearby maintained modules as the reference. Identify at most one concrete violation with reproducible lint/test evidence and a minimal correction. Do not impose patterns from unrelated repositories or perform broad rewrites.",
            interval=604800,
        ),
        Recipe(
            "owasp",
            "OWASP Security Hardening",
            "Find one evidenced security weakness within the fork's security policy.",
            "Review OWASP Top 10 concerns, prioritizing input handling, authorization checks and insecure defaults. Check SECURITY.md scope and existing advisories first. Use only synthetic local tests, never a deployed target. Return at most one demonstrated, non-embargoed issue with a runnable regression and specific acceptance criteria; never claim a full security certification.",
            interval=604800,
            category="Security",
        ),
        Recipe(
            "bug_triage",
            "Bug Report Triage",
            "Reproduce and prioritize existing bug reports without duplicating issues.",
            "Review up to five recent open bug reports in this fork. Identify duplicates, missing reproduction details, impact and recommended next action. Try safe local reproduction for one report within budget. Return existing issue numbers in the report; do not create duplicate issues, change labels, edit code or contact reporters. Labelled authorized issues are repaired by the separate event-driven intake.",
            kind="audit",
        ),
        Recipe(
            "release_readiness",
            "Release Readiness Review",
            "Review open PR checks and release blockers; leave approval and merge to engineers.",
            "Review up to five open PRs targeting the configured release branch. Summarize current SHAs, check status, test gaps, changelog needs and release blockers. Use GitHub readback, not agent claims, and cite existing PR URLs. Do not merge, tag, publish a release, deploy or call this report independent validation. Actual release validation is a separate fresh session.",
            interval=604800,
            kind="audit",
            category="Releases",
        ),
        Recipe(
            "cloudflare_audit",
            "Cloudflare Security Audit",
            "Review the configured account's audit logs for suspicious changes, without modifying infrastructure.",
            "Read only the configured Cloudflare account's audit logs for the last seven days using the supplied read-only credential. Summarize suspicious permission, DNS, firewall and configuration changes. Report time range, event count, pagination/retention gaps and safe event IDs. Never output tokens, IP addresses, actor emails or raw event payloads. Never modify Cloudflare resources. Report unavailable access as a blocker, never as a clean audit.",
            interval=604800,
            kind="audit",
            category="Security",
        ),
    )
}


def recipe_for(identity):
    if identity not in RECIPES:
        raise ValueError("Unknown automation")
    return RECIPES[identity]


def configuration_blocker(identity, settings):
    if identity == "cloudflare_audit" and not (
        settings.cloudflare_account_id and settings.cloudflare_audit_secret_id
    ):
        return "Configure CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AUDIT_SECRET_ID (a dedicated read-only secret in Devin)."
    return None


def attributed_jobs(jobs):
    """Resolve original automation through repair/integration/validation ancestry."""
    by_id = {job["id"]: job for job in jobs}
    cache = {}

    def origins(job, visited):
        if job["id"] in cache:
            return cache[job["id"]]
        if job["id"] in visited:
            return set()
        visited = visited | {job["id"]}
        payload = job["payload"]
        direct = payload.get("automation_id") or payload.get("schedule_id")
        if not direct and job["kind"] == "scan":
            direct = "discovery"  # Legacy scans predate the catalogue.
        result = {direct} if direct in RECIPES else set()
        parents = [job.get("parent_id"), *payload.get("implementation_jobs", [])]
        parents += [member.get("job_id") for member in payload.get("members", [])]
        for parent in parents:
            if parent in by_id:
                result |= origins(by_id[parent], visited)
        cache[job["id"]] = result
        return result

    return [
        {
            **job,
            "automations": [
                {"id": identity, "name": RECIPES[identity].name}
                for identity in sorted(origins(job, set()))
            ],
        }
        for job in jobs
    ]
