"""Durable progress comments for already-started independent validators."""

import hashlib
import re

from .links import safe_link
from .outbox import PublicationOutbox
from .readiness import current_pr


class ValidationActivityService:
    def __init__(self, settings, store, providers):
        self.settings = settings
        self.store = store
        self.providers = providers

    def tick(self):
        # Rebuild intentions from the durable ledger, including after a restart.
        # No provider calls or paid execution occur here; the outbox checks freshness.
        outbox = PublicationOutbox(self.settings, self.store, self.providers)
        for job in self.store.operational_jobs():
            if (
                job["kind"] != "validation"
                or job["state"] != "running"
                or not job.get("session_id")
                or not job.get("pr_number")
                or not re.fullmatch(r"[a-f0-9]{40}", job.get("candidate_sha") or "")
                or not safe_link(job.get("session_url"))
            ):
                continue
            revision = "started-" + hashlib.sha256(job["session_id"].encode()).hexdigest()[:24]
            body = (
                "## Independent Devin validation started\n\n"
                f"Devin is validating candidate `{job['candidate_sha']}`. "
                f"[Follow the active Devin session]({job['session_url']}).\n\n"
                "This is an automatic progress update, not approval or a passing release gate. "
                "Screenshots, video, API transcripts and test evidence will be checked before "
                "the final report. Human review and merge remain separate."
            )
            item = outbox.prepare_github(job["id"], job["pr_number"], body, {"revision": revision})
            item["payload"]["validation"] = None  # Progress has its own running-state policy.
            item["payload"]["activity"] = {
                "job_id": job["id"],
                "session_id": job["session_id"],
                "sha": job["candidate_sha"],
                "number": job["pr_number"],
            }
            self.store.queue_publication(**item)

    def current(self, metadata):
        def matches(job):
            return (
                job
                and job["kind"] == "validation"
                and job["state"] == "running"
                and job.get("session_id") == metadata["session_id"]
                and job.get("candidate_sha") == metadata["sha"]
                and job.get("pr_number") == metadata["number"]
            )

        if not matches(self.store.get(metadata["job_id"])):
            return False
        try:
            current_pr(self.settings, self.providers, metadata["number"], metadata["sha"])
        except ValueError:
            return False
        # The ledger may have finalized this job while GitHub was responding.
        return bool(matches(self.store.get(metadata["job_id"])))
