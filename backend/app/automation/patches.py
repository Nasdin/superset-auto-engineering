"""Explicitly labelled, owner-authored fork PRs use the same preparation/evidence pipeline."""

import re

from .dependencies import DependencyService


def eligible_patch(settings, pr):
    if (
        pr.get("state") != "open"
        or pr.get("draft")
        or pr.get("user", {}).get("login", "").lower() != settings.allowed_actor.lower()
        or settings.label not in [x.get("name") for x in pr.get("labels", [])]
        or (pr.get("base", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or pr.get("base", {}).get("ref") != settings.branch
        or (pr.get("head", {}).get("repo") or {}).get("full_name", "").lower()
        != settings.repo.lower()
        or not pr.get("head", {}).get("ref")
        or pr["head"]["ref"] == settings.branch
        or not re.fullmatch(r"[a-f0-9]{40}", pr.get("head", {}).get("sha", ""))
    ):
        raise ValueError(
            "Expected an owner-authored open fork PR with the repair label targeting the release branch"
        )


class PatchService(DependencyService):
    kind = "patch"
    intake_name = "patch"

    def accept(self, number, source, event_sha=None):
        for job in self.store.operational_jobs():
            if job["kind"] in {"repair", "integration"} and job["pr_number"] == number:
                return job  # Already owned by the issue/integration pipeline.
            if job["kind"] == "repair" and job["state"] in {
                "dispatching",
                "running",
                "unknown_effect",
                "needs_attention",
            }:
                raise ValueError(
                    "Repair handoff pending; PR intake will reconcile after it finishes"
                )
        return super().accept(number, source, event_sha)

    def preflight(self, job):
        for prior in self.store.operational_jobs():
            if (
                prior["kind"] in {"repair", "integration"}
                and prior["pr_number"] == job["pr_number"]
            ):
                self.store.update(
                    job["id"],
                    state="blocked",
                    error="PR is already owned by an issue repair or integration workflow",
                )
                return False
        return super().preflight(job)

    def enabled(self):
        return True  # Global paid-session switch still gates dispatch.

    def eligible(self, pr):
        eligible_patch(self.settings, pr)

    def accepts_author(self, pr):
        return pr.get("user", {}).get("login", "").lower() == self.settings.allowed_actor.lower()


def preparation_service(settings, store, providers, kind):
    cls = PatchService if kind == "patch" else DependencyService
    return cls(settings, store, providers)
