"""Read model joining cached public PR metadata to the complete execution ledger."""

from ..analytics.metrics import category


def pull_request_rows(pulls, jobs, publications):
    indexed = {
        pr["number"]: {
            **pr,
            "category": category(pr),
            "dependabot": pr["author"].lower() == "dependabot[bot]",
            "runs": [],
            "publications": [],
        }
        for pr in pulls
    }
    for job in jobs:
        payload = job["payload"]
        numbers = {job["pr_number"]}
        if job["kind"] == "validation":
            numbers.update(member["pr_number"] for member in payload.get("members", []))
        for number in numbers - {None}:
            row = indexed.setdefault(
                number,
                {
                    "number": number,
                    "title": payload.get("title", f"PR #{number}"),
                    "author": payload.get("author", "Not imported yet"),
                    "category": "dependency"
                    if payload.get("work_type") == "dependency"
                    else "other",
                    "dependabot": payload.get("work_type") == "dependency",
                    "state": "not_imported",
                    "updated_at": None,
                    "runs": [],
                    "publications": [],
                },
            )
            row["runs"].append(job)
    for row in indexed.values():
        row["runs"].sort(key=lambda job: job["created"], reverse=True)
        ids = {job["id"] for job in row["runs"]}
        row["publications"] = [
            pub
            for pub in publications
            if pub["key"].split(":")[1] in ids
            and (
                pub["key"].startswith("slack:")
                or pub["key"].rsplit(":", 1)[-1] == str(row["number"])
            )
        ]
    return sorted(indexed.values(), key=lambda row: row["number"], reverse=True)
