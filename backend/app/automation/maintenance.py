"""Bounded automation-created PRs use the same independent validation outbox."""

import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .outbox import PublicationOutbox


class MaintenanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_complete: StrictBool
    summary: str = Field(min_length=1, max_length=12000)
    tests: list[str]
    pr_url: str
    candidate_sha: str
    blocker: str = Field(max_length=4000)


def finish_maintenance(settings, store, providers, job, result):
    report = MaintenanceResult.model_validate(result)
    if not report.task_complete:
        raise ValueError("Maintenance requires a final structured handoff")
    if result.get("blocker"):
        store.update(
            job["id"], state="needs_attention", error=str(result["blocker"])[:500], result=result
        )
        return
    if not result.get("pr_url"):
        if not result.get("tests") or result.get("candidate_sha"):
            raise ValueError("A clean scan needs recorded checks and no candidate")
        store.commit_handoff(
            job["id"], values={"state": "completed", "result": result, "error": None}
        )
        return
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(settings.repo)}/pull/(\d+)", result["pr_url"]
    )
    if not match:
        raise ValueError("Maintenance PR must target the configured fork")
    number = int(match[1])
    pr = providers.pr(number)
    sha = pr["head"]["sha"]
    if (
        pr["state"] != "open"
        or pr["base"]["repo"]["full_name"] != settings.repo
        or pr["base"]["ref"] != settings.branch
        or pr["head"]["repo"]["full_name"] != settings.repo
        or pr["head"]["ref"] != f"cognition/automation/{job['id'][:12]}"
        or not re.fullmatch(r"[a-f0-9]{40}", sha)
        or sha != result.get("candidate_sha")
    ):
        raise ValueError("Maintenance PR branch, target or candidate changed")
    publication = PublicationOutbox(settings, store, providers).prepare_github(
        job["id"],
        number,
        f"Automation prepared a scoped change at `{sha}`. Independent release validation is queued. This is not approval. Devin: {job['session_url']}",
    )
    store.commit_handoff(
        job["id"],
        values={
            "state": "prepared",
            "pr_number": number,
            "candidate_sha": sha,
            "result": result,
            "error": None,
        },
        publications=[publication],
        followups=[
            {
                "key": f"validation:{settings.repo}:{number}:{sha}",
                "kind": "validation",
                "payload": {
                    **job["payload"],
                    "implementation_jobs": [job["id"]],
                    "work_type": "pr_validation",
                    "tracked_pr": True,
                    "head_ref": pr["head"]["ref"],
                },
                "parent_id": job["id"],
                "candidate_sha": sha,
                "pr_number": number,
            }
        ],
    )
