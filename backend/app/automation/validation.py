"""Independent evidence acceptance and candidate freshness."""

import hashlib
import json

from .artifacts import EvidenceArchive, attachment_records, complete_handoff
from .config import Settings
from .evidence import assess_evidence
from .outbox import PublicationOutbox
from .ports import ProviderGateway
from .redaction import provider_secrets, sanitize
from .reports import ReleaseReportBuilder
from .store import Store


class ValidationService:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        self.settings = settings
        self.store = store
        self.providers = providers
        self.outbox = PublicationOutbox(settings, store, providers)
        self.reports = ReleaseReportBuilder()

    def is_current(self, job):
        pr = self.providers.pr(job["pr_number"])
        eligible = (
            pr["state"] == "open"
            and pr["base"]["repo"]["full_name"].lower() == self.settings.repo.lower()
            and pr["base"]["ref"] == self.settings.branch
        )
        if job["payload"].get("work_type") == "remediation":
            from .readiness import current_pr

            try:
                current_pr(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
                eligible = eligible and pr["head"]["ref"] == job["payload"]["head_ref"]
            except ValueError:
                eligible = False
        if job["payload"].get("work_type") == "pr_validation":
            from .pr_validation import eligible_validation

            try:
                eligible_validation(
                    self.settings, pr, tracked=job["payload"].get("tracked_pr", False)
                )
                eligible = eligible and pr["head"]["ref"] == job["payload"]["head_ref"]
            except ValueError:
                eligible = False
        if job["payload"].get("work_type") in {"dependency", "patch"}:
            from .patches import preparation_service

            try:
                preparation_service(
                    self.settings, self.store, self.providers, job["payload"]["work_type"]
                ).eligible(pr)
                eligible = eligible and pr["head"]["ref"] == job["payload"]["head_ref"]
            except ValueError:
                eligible = False
        if not eligible or pr["head"]["sha"] != job["candidate_sha"]:
            self.store.supersede_validation(
                job, pr["head"]["sha"] if eligible else None, self.settings.repo
            )
            return False
        return True

    def finish_validation(self, job, result):
        if not self.is_current(job):
            return
        attachments = attachment_records(self.providers.attachments(job["session_id"]))
        result = complete_handoff(self.providers, result, attachments)
        result = sanitize(result, provider_secrets(self.settings))
        implementation_ids = job["payload"].get("implementation_jobs", [job["parent_id"]])
        implementations = [self.store.get(jid) for jid in implementation_ids]
        assessment = assess_evidence(
            candidate_sha=job["candidate_sha"],
            validator_session=job["session_id"],
            implementation_sessions=[
                item.get("session_id") if item else None for item in implementations
            ],
            result=result,
            attachments=attachments,
            external_implementation=job["payload"].get("implementation_origin") == "external_pr"
            and job["payload"].get("work_type") == "pr_validation"
            and self.store.has_audit(job["id"], "session_created"),
        )
        valid = assessment.passed
        ci = None
        if valid:
            from .readiness import ci_status

            ci = ci_status(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
        failures = list(assessment.failures)
        if ci and ci["state"] == "failure":
            failures.append("GitHub CI reports failing checks for this exact revision")
        valid = valid and (ci is None or ci["state"] == "success")
        status = (
            "awaiting_ci"
            if ci and ci["state"] == "pending"
            else "review_ready"
            if valid
            else "validation_failed"
        )
        result = {
            **result,
            "artifacts": EvidenceArchive(self.settings, self.providers).publish(
                assessment.artifacts, attachments
            ),
            "provenance": "independent_devin_session" if valid else "unverified_validation",
            "gate_failures": failures,
            "ci": ci,
            "gate": status,
        }
        # Downloads can be slow. Never revive a gate superseded while collecting proof.
        if self.store.get(job["id"])["state"] == "stale" or not self.is_current(job):
            return
        from .remediation import RemediationService

        followups = (
            RemediationService(self.settings, self.store, self.providers).followups(job, result)
            if status == "validation_failed"
            else []
        )
        result["recovery"] = {
            "automatic": bool(followups),
            "attempt": job["payload"].get("recovery_attempt", 0),
            "limit": self.settings.max_remediation_attempts,
            "next": followups[0]["kind"] if followups else None,
        }
        report = self.reports.build(job, result, status)
        targets = [job["pr_number"]]
        if job["payload"].get("issue_number"):
            targets.append(job["payload"]["issue_number"])
        for member in job["payload"].get("members", []):
            targets += [member["pr_number"], member["issue_number"]]
        metadata = {
            "job_id": job["id"],
            "targets": [{"number": job["pr_number"], "sha": job["candidate_sha"]}]
            + [
                {"number": m["pr_number"], "sha": m["sha"]}
                for m in job["payload"].get("members", [])
            ],
        }
        if self.settings.autonomous_remediation:
            metadata["revision"] = hashlib.sha256(
                json.dumps(
                    {"handoff": result.get("handoff_attachment_id"), "status": status, "ci": ci},
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:16]
        elif result.get("handoff_attachment_id"):
            metadata["revision"] = result["handoff_attachment_id"]
        publications = [
            self.outbox.prepare_github(job["id"], number, report, validation=metadata)
            for number in dict.fromkeys(targets)
        ]
        if self.settings.slack_token and self.settings.slack_channel:
            publications.append(self.outbox.prepare_slack(job, report, validation=metadata))
        if valid and self.providers.pr(job["pr_number"]).get("draft", False):
            publications.append(self.outbox.prepare_ready(job, metadata.get("revision", "initial")))
        if not self.store.commit_validation(
            job["id"],
            status,
            result,
            None if valid or status == "awaiting_ci" else "; ".join(failures),
            publications,
            followups,
        ):
            return
        lessons = self.store.recall("repository_lessons", [])
        lessons = [x for x in lessons if x["candidate_sha"] != job["candidate_sha"]]
        self.store.remember(
            "repository_lessons",
            (
                lessons
                + [
                    {
                        "candidate_sha": job["candidate_sha"],
                        "status": status,
                        "summary": result.get("summary", "")[:1000],
                    }
                ]
            )[-20:],
        )

    def refresh_readiness(self):
        for job in self.store.operational_jobs():
            if job["state"] != "review_ready":
                continue
            self.is_current(job)
