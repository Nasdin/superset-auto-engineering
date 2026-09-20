"""Prepare a bot-owned PR in the fork, then independently validate its final head."""

import re
import time

from .outbox import PublicationOutbox

ACTIVE = {"queued", "dispatching", "running", "unknown_effect", "needs_attention"}


def eligible_pr(settings, pr):
    if (
        pr.get("state") != "open"
        or pr.get("draft")
        or pr.get("user", {}).get("login") != "dependabot[bot]"
        or pr.get("user", {}).get("type") != "Bot"
        or (pr.get("base", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or pr.get("base", {}).get("ref") != settings.branch
        or (pr.get("head", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or not pr.get("head", {}).get("ref")
        or not re.fullmatch(r"[a-f0-9]{40}", pr.get("head", {}).get("sha", ""))
    ):
        raise ValueError(
            "Expected an open Dependabot PR from this fork into the configured release branch"
        )


class DependencyService:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    def accept(self, number, source, event_sha=None):
        if not self.settings.dependabot_enabled:
            raise ValueError("Dependabot automation is disabled")
        pr = self.providers.pr(number)
        eligible_pr(self.settings, pr)
        sha = pr["head"]["sha"]
        if event_sha is not None and event_sha != sha:
            return {"status": "ignored", "reason": "Superseded PR event"}
        related = [
            j
            for j in self.store.operational_jobs()
            if j["pr_number"] == number and j["payload"].get("work_type") == "dependency"
        ]
        # Coalesce our own pushes and uncertain in-flight work. No second paid session.
        active = next((j for j in related if j["state"] in ACTIVE), None)
        if active:
            return active
        validations = [j for j in related if j["kind"] == "validation"]
        current = next(
            (j for j in validations if j["candidate_sha"] == sha and j["state"] != "stale"), None
        )
        if current:
            return current
        if validations:
            latest = validations[0]
            if latest["state"] != "stale":
                self.store.supersede_validation(latest, sha, self.settings.repo)
            else:
                key = self.fresh_key(f"validation:{self.settings.repo}:{number}:{sha}")
                self.store.enqueue(
                    key,
                    "validation",
                    latest["payload"],
                    parent_id=latest["parent_id"],
                    candidate_sha=sha,
                    pr_number=number,
                )
            return {
                "status": "accepted",
                "reason": "Changed or reopened PR requires fresh validation",
            }
        same = next(
            (j for j in related if j["candidate_sha"] == sha and j["state"] != "stale"), None
        )
        if same:
            return same
        key = f"dependency:{self.settings.repo}:{number}:{sha}"
        return self.store.enqueue(
            self.fresh_key(key),
            "dependency",
            {
                "title": pr["title"],
                "pr_url": pr["html_url"],
                "source": source,
                "work_type": "dependency",
                "original_head": sha,
                "head_ref": pr["head"]["ref"],
                "base_sha": pr["base"]["sha"],
                "author": "dependabot[bot]",
            },
            candidate_sha=sha,
            pr_number=number,
        )

    def fresh_key(self, key):
        while (prior := self.store.by_key(key)) and prior["state"] == "stale":
            key += f":after:{prior['id']}"
        return key

    def webhook(self, number, delivery, sha):
        if self.store.has_delivery(delivery):
            return {"status": "duplicate"}
        job = self.accept(number, "dependabot_webhook", sha)
        self.store.record_delivery(delivery)
        return {
            "status": job.get("status", "accepted"),
            "job_id": job.get("id"),
            "reason": job.get("reason"),
        }

    def poll(self):
        if not self.settings.dependabot_enabled:
            return
        # Rotate through bounded pages so missed events on older PRs can recover.
        page = self.store.recall("dependabot_next_page", 1)
        prs = self.providers.gh(
            "GET",
            f"repos/{self.settings.repo}/pulls",
            params={"state": "open", "base": self.settings.branch, "per_page": 100, "page": page},
        )
        accepted = 0
        for pr in prs:
            if pr.get("user", {}).get("login") != "dependabot[bot]":
                continue
            try:
                self.accept(pr["number"], "dependabot_poll")
                accepted += 1
            except ValueError:
                continue
        self.store.remember("dependabot_next_page", page + 1 if len(prs) == 100 else 1)
        self.store.remember(
            "dependabot_poll", {"at": time.time(), "eligible": accepted, "bounded_at": 100}
        )

    def preflight(self, job):
        if not self.settings.dependabot_enabled:
            self.store.update(job["id"], state="blocked", error="Dependabot automation is disabled")
            return False
        pr = self.providers.pr(job["pr_number"])
        try:
            eligible_pr(self.settings, pr)
        except ValueError as error:
            self.store.update(job["id"], state="stale", error=str(error))
            return False
        if (
            pr["head"]["sha"] != job["candidate_sha"]
            or pr["head"]["ref"] != job["payload"]["head_ref"]
        ):
            self.store.update(
                job["id"],
                state="stale",
                error="PR changed before dispatch; waiting for current-head intake",
            )
            return False
        return True

    def finish(self, job, result):
        if result.get("blocker"):
            self.store.update(
                job["id"],
                state="needs_attention",
                error="Dependency blocker: " + str(result["blocker"])[:250],
                result=result,
            )
            return
        pr = self.providers.pr(job["pr_number"])
        eligible_pr(self.settings, pr)
        expected_url = f"https://github.com/{self.settings.repo}/pull/{job['pr_number']}"
        sha = pr["head"]["sha"]
        if (
            result.get("pr_url") != expected_url
            or result.get("candidate_sha") != sha
            or pr["head"]["ref"] != job["payload"]["head_ref"]
        ):
            raise ValueError(
                "Dependency handoff must match the original PR, head branch and live SHA"
            )
        payload = {**job["payload"], "implementation_jobs": [job["id"]]}
        self.store.enqueue(
            f"validation:{self.settings.repo}:{job['pr_number']}:{sha}",
            "validation",
            payload,
            parent_id=job["id"],
            candidate_sha=sha,
            pr_number=job["pr_number"],
        )
        PublicationOutbox(self.settings, self.store, self.providers).publish(
            job["id"],
            job["pr_number"],
            f"Dependabot update prepared at `{sha}`.\n\nDevin: {job['session_url']}\n\nFresh independent validation is queued. This is not release approval. Evidence will be posted to this PR.",
        )
        self.store.update(job["id"], state="prepared", candidate_sha=sha, result=result)
