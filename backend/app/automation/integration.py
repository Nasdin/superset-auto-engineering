"""Assemble immutable integration candidates with resumable GitHub writes."""

import hashlib
import json
import time

from .config import Settings
from .ports import ProviderGateway
from .providers import ProviderError
from .store import Store


class IntegrationService:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        self.settings = settings
        self.store = store
        self.providers = providers

    def schedule_batch(self):
        jobs = self.store.operational_jobs()
        taken = {
            m["job_id"] for j in jobs if j["kind"] == "integration" for m in j["payload"]["members"]
        }
        ready = [j for j in jobs if j["state"] == "implemented" and j["id"] not in taken]
        # A short quiet period coalesces commits; other queued/running repairs complete first.
        if not ready or any(
            j["kind"] == "repair" and j["state"] in {"queued", "running", "dispatching"}
            for j in jobs
        ):
            return None
        if time.time() - max(j["updated"] for j in ready) < self.settings.batch_seconds:
            return None
        members = [
            {
                "job_id": j["id"],
                "pr_number": j["pr_number"],
                "sha": j["candidate_sha"],
                "issue_number": j["payload"]["issue_number"],
            }
            for j in sorted(ready, key=lambda j: j["created"])
        ]
        digest = hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()[:20]
        return self.store.enqueue(
            "integration:" + digest,
            "integration",
            {
                "members": members,
                "source": "batch",
                "title": f"Integrate {len(members)} completed workstreams",
            },
        )

    def assemble_candidate(self, job):
        members = job["payload"]["members"]
        checkpoint = job.get("result") or {}
        branch = "cognition/integration/" + job["id"][:12]
        if not checkpoint:
            base = self.providers.gh(
                "GET", f"repos/{self.settings.repo}/commits/{self.settings.branch}"
            )["sha"]
            checkpoint = {
                "base_sha": base,
                "head_sha": base,
                "applied": 0,
                "branch": branch,
            }
            self.store.update(job["id"], result=checkpoint)
        base = checkpoint["base_sha"]
        try:
            current = self.providers.gh(
                "GET", f"repos/{self.settings.repo}/git/ref/heads/{branch}"
            )["object"]["sha"]
        except ProviderError as e:
            if e.status != 404:
                raise
            self.providers.gh(
                "POST",
                f"repos/{self.settings.repo}/git/refs",
                json={"ref": "refs/heads/" + branch, "sha": base},
            )
            current = base
        for index, member in enumerate(members):
            pr = self.providers.pr(member["pr_number"])
            if (
                pr["state"] != "open"
                or pr["head"]["sha"] != member["sha"]
                or pr["base"]["ref"] != self.settings.branch
                or pr["base"]["repo"]["full_name"].lower() != self.settings.repo.lower()
            ):
                raise ValueError(
                    "Component PR changed before integration; rebuild from fresh component revisions"
                )
            if index < checkpoint["applied"]:
                continue
            expected = checkpoint["head_sha"]
            if current != expected:
                # Reconcile a merge whose response/checkpoint was lost. Accept only
                # the intended merge parents or an exact fast-forward component.
                commit = self.providers.gh(
                    "GET", f"repos/{self.settings.repo}/git/commits/{current}"
                )
                parents = {x["sha"] for x in commit["parents"]}
                if current != member["sha"] and parents != {expected, member["sha"]}:
                    raise ValueError(
                        "Integration branch has an unexpected commit; operator review required"
                    )
                if current == member["sha"]:
                    comparison = self.providers.gh(
                        "GET", f"repos/{self.settings.repo}/compare/{expected}...{current}"
                    )
                    if comparison["merge_base_commit"]["sha"] != expected:
                        raise ValueError("Unexpected integration fast-forward")
            else:
                merge = self.providers.gh(
                    "POST",
                    f"repos/{self.settings.repo}/merges",
                    json={
                        "base": branch,
                        "head": member["sha"],
                        "commit_message": f"Integrate PR #{member['pr_number']} for independent validation",
                    },
                )
                current = (
                    merge["sha"]
                    if merge
                    else self.providers.gh(
                        "GET", f"repos/{self.settings.repo}/git/ref/heads/{branch}"
                    )["object"]["sha"]
                )
            checkpoint = {**checkpoint, "head_sha": current, "applied": index + 1}
            self.store.update(job["id"], result=checkpoint)
            self.store.audit(
                job["id"],
                "integration_component",
                {
                    "pr": member["pr_number"],
                    "sha": member["sha"],
                    "integrated_sha": current,
                },
            )
        if current != checkpoint["head_sha"]:
            raise ValueError("Completed integration branch changed externally")
        body = (
            "Integration candidate for independent validation. Do not merge before reviewing evidence.\n\n"
            + "\n".join(
                f"- #{m['pr_number']} at `{m['sha']}` (issue #{m['issue_number']})" for m in members
            )
            + f"\n\nExact candidate: `{current}`."
        )
        matches = self.providers.gh(
            "GET",
            f"repos/{self.settings.repo}/pulls",
            params={
                "state": "all",
                "head": self.settings.repo.split("/")[0] + ":" + branch,
                "base": self.settings.branch,
            },
        )
        pr = next((x for x in matches if x["head"]["ref"] == branch), None)
        if not pr:
            pr = self.providers.gh(
                "POST",
                f"repos/{self.settings.repo}/pulls",
                json={
                    "title": f"Cognition integration: {len(members)} workstream(s)",
                    "head": branch,
                    "base": self.settings.branch,
                    "body": body,
                    "draft": True,
                },
            )
        elif pr["state"] != "open" or pr["head"]["sha"] != current:
            raise ValueError("Existing integration PR is not open at expected revision")
        payload = {
            "issue_number": members[0]["issue_number"],
            "title": job["payload"]["title"],
            "source": "integration",
            "members": members,
            "implementation_jobs": [m["job_id"] for m in members],
            "base_sha": base,
            "branch": branch,
        }
        self.store.enqueue(
            f"validation:{self.settings.repo}:{pr['number']}:{current}",
            "validation",
            payload,
            parent_id=members[0]["job_id"],
            candidate_sha=current,
            pr_number=pr["number"],
        )
        self.store.update(
            job["id"],
            state="integrated",
            candidate_sha=current,
            pr_number=pr["number"],
            result={**checkpoint, "pr_url": pr["html_url"], "members": members},
        )
