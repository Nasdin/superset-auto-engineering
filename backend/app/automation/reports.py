"""Build review reports without network or persistence side effects."""

import html


def plain_report(value):
    text = html.escape(str(value)).replace("@", "@\u200b")
    for char in ["[", "]", "*", "_", "`"]:
        text = text.replace(char, "\\" + char)
    return text


class ReleaseReportBuilder:
    def build(self, job, result, status):
        lines = [
            f"## Cognition release validation — {status.replace('_', ' ')}",
            f"Candidate: `{job['candidate_sha']}`",
            f"Independent Devin validator: {job['session_url']}",
            "This is independently collected agent evidence for human review, not a merge or deployment approval.",
            "",
            plain_report(result.get("summary", "")),
            "",
            "| Check | Result | Command |",
            "|---|---|---|",
        ]
        for c in result.get("checks", []):

            def clean(value):
                return plain_report(
                    str(value).replace("|", "/").replace("\n", " ").replace("`", "\u2032")[:300]
                )

            lines.append(
                f"| {clean(c['name'])} | {'pass' if c.get('passed') else 'FAIL'} | `{clean(c.get('command', ''))}` |"
            )
        lines += ["", "### Screenshots, video and execution evidence"]
        lines += [
            f"- [{a['kind']}: {plain_report(a['name'])}](<{a['url']}>)" for a in result["artifacts"]
        ]
        if not result["artifacts"]:
            lines.append("No provider-confirmed artifacts available. The evidence gate is blocked.")
        if result.get("blocker"):
            lines += ["", "Blocker: " + plain_report(result["blocker"])]
        return "\n".join(lines)
