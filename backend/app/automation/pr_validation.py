"""Validate existing fork PRs without editing them; coalesce events at the current head."""

import re
import time

from .dependencies import ACTIVE

VALIDATE_LABEL = "cognition:validate"


def eligible_validation(settings, pr, *, tracked=False):
    if (
        pr.get("state") != "open"
        or (pr.get("draft") and not tracked)
        or (pr.get("base", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or pr.get("base", {}).get("ref") != settings.branch
        or (pr.get("head", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or not pr.get("head", {}).get("ref")
        or pr["head"]["ref"] == settings.branch
        or not re.fullmatch(r"[a-f0-9]{40}", pr.get("head", {}).get("sha", ""))
        or (not tracked and VALIDATE_LABEL not in [x.get("name") for x in pr.get("labels", [])])
    ):
        raise ValueError(
            "Validation requires a tracked or cognition:validate-labelled open PR within the configured fork and release branch"
        )


class PullRequestValidationService:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    def accept(self, number, source, event_sha=None):
        jobs = self.store.operational_jobs()
        related = [j for j in jobs if j["pr_number"] == number]
        if any(j["kind"] in {"dependency", "patch"} for j in related):
            raise ValueError("This PR uses its existing preparation and validation pipeline")
        tracked = bool(related)
        pr = self.providers.pr(number)
        eligible_validation(self.settings, pr, tracked=tracked)
        sha = pr["head"]["sha"]
        if event_sha is not None and event_sha != sha:
            return {"status": "ignored", "reason": "Superseded PR event"}
        # Own implementation pushes are handled after its structured handoff.
        if any(
            j["kind"] in {"repair", "patch", "dependency", "maintenance"} and j["state"] in ACTIVE
            for j in related
        ):
            return {"status": "deferred", "reason": "Implementation handoff pending"}
        validations = [j for j in related if j["kind"] == "validation"]
        current = next(
            (j for j in validations if j["candidate_sha"] == sha and j["state"] != "stale"), None
        )
        if current:
            return current
        # Never abandon a paid/uncertain validator to start another. Polling will reconcile later.
        if any(
            j["state"] in {"running", "dispatching", "unknown_effect", "needs_attention"}
            for j in validations
        ):
            return {"status": "deferred", "reason": "Prior validator must finish or be reconciled"}
        originals = [
            j
            for j in related
            if j["kind"] in {"repair", "patch", "dependency", "maintenance", "integration"}
        ]
        if originals and not validations and all(j["candidate_sha"] == sha for j in originals):
            return {
                "status": "deferred",
                "reason": "Original candidate follows its existing integration pipeline",
            }
        for old in validations:
            if old["state"] != "stale":
                self.store.supersede_validation(old, None, self.settings.repo)
        implementation_ids = {
            j["id"]
            for j in originals
            if j["kind"] in {"repair", "patch", "dependency", "maintenance"}
        }
        for prior in related:
            implementation_ids.update(prior["payload"].get("implementation_jobs", []))
            implementation_ids.update(m["job_id"] for m in prior["payload"].get("members", []))
        # Preserve known provenance even after an engineer edits an integration PR.
        # Missing ledger records must fail closed rather than become "external".
        implementation = [self.store.get(jid) for jid in sorted(implementation_ids)]
        origin = "tracked_devin" if implementation_ids else "external_pr"
        payload = {
            "title": pr["title"],
            "source": source,
            "work_type": "pr_validation",
            "head_ref": pr["head"]["ref"],
            "base_sha": pr["base"]["sha"],
            "author": pr["user"]["login"],
            "implementation_origin": origin,
            "implementation_jobs": sorted(implementation_ids),
            "tracked_pr": tracked,
            "prior_implementation_shas": [j["candidate_sha"] for j in implementation if j],
        }
        key = f"validation:{self.settings.repo}:{number}:{sha}"
        while (prior := self.store.by_key(key)) and prior["state"] == "stale":
            key += f":after:{prior['id']}"
        return self.store.enqueue(
            key,
            "validation",
            payload,
            parent_id=next(iter(sorted(implementation_ids)), None),
            candidate_sha=sha,
            pr_number=number,
        )

    def poll(self):
        page = self.store.recall("pr_validation_next_page", 1)
        prs = self.providers.gh(
            "GET",
            f"repos/{self.settings.repo}/pulls",
            params={"state": "open", "base": self.settings.branch, "per_page": 100, "page": page},
        )
        for pr in prs:
            try:
                self.accept(pr["number"], "pr_validation_poll")
            except ValueError:
                continue
        self.store.remember("pr_validation_next_page", page + 1 if len(prs) == 100 else 1)
        self.store.remember("pr_validation_poll", {"at": time.time()})
