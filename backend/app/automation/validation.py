"""Independent evidence acceptance and candidate freshness."""

from .config import Settings
from .evidence import assess_evidence
from .outbox import PublicationOutbox
from .ports import ProviderGateway
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
        if job["payload"].get("work_type") == "dependency":
            from .dependencies import eligible_pr

            try:
                eligible_pr(self.settings, pr)
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
        implementation_ids = job["payload"].get("implementation_jobs", [job["parent_id"]])
        implementations = [self.store.get(jid) for jid in implementation_ids]
        assessment = assess_evidence(
            candidate_sha=job["candidate_sha"],
            validator_session=job["session_id"],
            implementation_sessions=[
                item.get("session_id") if item else None for item in implementations
            ],
            result=result,
            attachments=self.providers.attachments(job["session_id"]),
        )
        valid = assessment.passed
        status = "review_ready" if valid else "validation_failed"
        result = {
            **result,
            "artifacts": assessment.artifacts,
            "provenance": "independent_devin_session" if valid else "unverified_validation",
            "gate_failures": assessment.failures,
            "gate": status,
        }
        report = self.reports.build(job, result, status)
        targets = [job["pr_number"]]
        if job["payload"].get("issue_number"):
            targets.append(job["payload"]["issue_number"])
        for member in job["payload"].get("members", []):
            targets += [member["pr_number"], member["issue_number"]]
        for number in dict.fromkeys(targets):
            self.outbox.publish(job["id"], number, report)
        if self.settings.slack_token and self.settings.slack_channel:
            self.outbox.publish_slack(job, report)
        self.store.update(
            job["id"],
            state=status,
            result=result,
            error=(None if valid else "; ".join(assessment.failures)),
        )
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
