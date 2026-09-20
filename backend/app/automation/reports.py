"""Build bounded, credential-redacted review reports without provider side effects."""

import html
import re

from .execution_evidence import count
from .links import safe_link
from .redaction import redact_text, sanitize


def plain_report(value):
    text = html.escape(redact_text(value)).replace("@", "@\u200b")
    for char in ["[", "]", "*", "_", "`"]:
        text = text.replace(char, "\\" + char)
    return text


def code_block(value, language="text", limit=2000):
    text = redact_text(value)[:limit]
    fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", text)), default=0))
    return f"{fence}{language}\n{text}\n{fence}"


def coverage_ratio(covered, total):
    if not count(covered) or not count(total) or total == 0 or covered > total:
        return "Unavailable"
    return f"{covered}/{total} ({100 * covered / total:.1f}%)"


class ReleaseReportBuilder:
    def build(self, job, result, status):
        result = sanitize(result)
        lines = [
            f"## Cognition release validation — {status.replace('_', ' ')}",
            f"Candidate: `{job['candidate_sha']}`",
            f"Independent Devin validator: {job['session_url']}",
            "Devin collects the evidence; the configured GitHub integration publishes this reply. Human review and merge remain separate.",
            "Artifact ownership and the evidence manifest are checked. Review linked execution output; attachment metadata alone cannot prove its contents.",
            "",
            plain_report(str(result.get("summary", ""))[:1800]),
            "",
        ]
        if job.get("payload", {}).get("members"):
            lines += [
                "### Integrated workstreams",
                "This report tests the integrated candidate above, with these component revisions:",
            ]
            lines += [f"- PR #{m['pr_number']} at `{m['sha']}`" for m in job["payload"]["members"]]
        lines += ["", "| Check | Result | Command |", "|---|---|---|"]
        for check in result.get("checks", []):

            def clean(value):
                return plain_report(
                    str(value).replace("|", "/").replace("\n", " ").replace("`", "\u2032")[:300]
                )

            lines.append(
                f"| {clean(check['name'])} | {'pass' if check.get('passed') else 'FAIL'} | `{clean(check.get('command', ''))}` |"
            )
        lines += ["", "### API requests executed against running Superset"]
        requests = result.get("api_requests")
        for request in (requests if isinstance(requests, list) else [])[:10]:
            if not isinstance(request, dict):
                continue
            lines += [
                "",
                "#### " + plain_report(str(request.get("name", "API request"))[:120]),
                code_block(request.get("curl", "Not recorded"), "bash"),
                f"Expected HTTP {plain_report(request.get('expected_status', 'unknown'))}; observed HTTP {plain_report(request.get('actual_status', 'unknown'))}.",
                "Assertion: " + plain_report(str(request.get("assertion", "Not recorded"))[:500]),
                code_block(request.get("response_excerpt", "Not recorded"), "text", 1000),
            ]
        if not requests:
            lines.append(
                "Unavailable: no executed API transcript recorded. This is not a passing API check."
            )
        lines += ["", "### Tests and coverage"]
        tests = result.get("test_results")
        if isinstance(tests, dict):
            lines += [
                f"Tests: {plain_report(tests.get('passed', 'unknown'))} passed · {plain_report(tests.get('failed', 'unknown'))} failed · {plain_report(tests.get('skipped', 'unknown'))} skipped.",
                code_block(tests.get("command", "Not recorded"), "bash"),
            ]
        else:
            lines.append("Test totals unavailable.")
        coverage = result.get("coverage")
        if isinstance(coverage, dict):
            lines += [
                "Measured scope: " + plain_report(str(coverage.get("scope", "Not recorded"))[:500]),
                "Line coverage: "
                + coverage_ratio(coverage.get("lines_covered"), coverage.get("lines_total")),
                "Branch coverage: "
                + coverage_ratio(coverage.get("branches_covered"), coverage.get("branches_total")),
                code_block(coverage.get("command", "Not recorded"), "bash"),
                "These are scoped measurements, not overall Superset coverage. No arbitrary coverage threshold is implied.",
            ]
        else:
            lines.append("Coverage unavailable; no percentage claimed.")
        lines += ["", "### Screenshots, video and execution evidence"]
        artifacts = result.get("artifacts", [])
        for artifact in artifacts:
            if not safe_link(artifact.get("url")):
                continue
            name = plain_report(str(artifact.get("name", "Evidence"))[:180]).replace("\n", " ")
            lines.append(f"- [{artifact['kind']}: {name}](<{artifact['url']}>)")
            if artifact["kind"] == "screenshot":
                lines.append(f"![Superset running — {name}](<{artifact['url']}>)")
        if not artifacts:
            lines.append("No provider-confirmed artifacts available. The evidence gate is blocked.")
        if result.get("gate_failures"):
            lines += ["", "### Evidence gate gaps"] + [
                "- " + plain_report(f) for f in result["gate_failures"]
            ]
        if result.get("blocker"):
            lines += ["", "Blocker: " + plain_report(result["blocker"])]
        return "\n".join(lines)
