"""Bounded, durable Devin repair and fresh independent revalidation."""

from .execution_evidence import count
from .outbox import PublicationOutbox
from .readiness import ci_status, current_pr


class RemediationService:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    def followups(self, job, result):
        """Pure follow-up intent after fresh scope read; caller commits it with the gate."""
        if not self.settings.autonomous_remediation:
            return []
        if result.get("candidate_sha") != job["candidate_sha"]:
            return []
        if any(
            "independence" in f.lower() or "sha does not match" in f.lower()
            for f in result.get("gate_failures", [])
        ):
            return []  # Provenance corruption is not authority to edit a branch.
        attempt = job["payload"].get("recovery_attempt", 0) + 1
        if attempt > self.settings.max_remediation_attempts:
            return []
        try:
            pr = current_pr(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
        except ValueError:
            return []
        tests = result.get("test_results")
        # Numeric failures override an agent's contradictory passing summary.
        failed_tests = (
            isinstance(tests, dict) and count(tests.get("failed")) and tests["failed"] > 0
        )
        code_failure = (
            failed_tests
            or (result.get("ci") or {}).get("state") == "failure"
            or any(
                c.get("passed") is False
                and c.get("name") in {"regression", "api", "browser", "database"}
                for c in result.get("checks", [])
                if isinstance(c, dict)
            )
        )
        payload = {
            **job["payload"],
            "title": pr.get("title", job["payload"].get("title", "PR remediation")),
            "source": "automatic_validation_recovery",
            "head_ref": pr["head"]["ref"],
            "recovery_attempt": attempt,
            "failed_validation_job": job["id"],
            "recovery_root": job["payload"].get("recovery_root", job["id"]),
            "recovery_mode": "code_repair" if code_failure else "evidence_recollection",
            "failure_context": {
                k: result.get(k)
                for k in (
                    "summary",
                    "blocker",
                    "checks",
                    "test_results",
                    "api_requests",
                    "gate_failures",
                    "ci",
                )
            },
            "implementation_jobs": job["payload"].get("implementation_jobs", [job["parent_id"]]),
            "automation_actor": "devin",
            "publisher": "configured_github_integration",
            "failure_publication_key": result.get("failure_publication_key"),
        }
        return [
            {
                "key": f"recovery:{job['id']}",
                "kind": "remediation" if code_failure else "validation",
                "payload": payload,
                "parent_id": job["id"],
                "candidate_sha": job["candidate_sha"],
                "pr_number": job["pr_number"],
            }
        ]

    def preflight_validation(self, job):
        """Cheap CI failure goes to Devin before paying for a runtime validator."""
        ci = ci_status(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
        if ci["state"] != "failure" or self.settings.capture_failure_evidence:
            return True
        result = {
            "candidate_sha": job["candidate_sha"],
            "passed": False,
            "task_complete": True,
            "summary": "GitHub CI failed before independent runtime validation started.",
            "blocker": "Failing GitHub checks require remediation",
            "checks": [],
            "artifacts": [],
            "ci": ci,
            "gate": "validation_failed",
            "gate_failures": ["GitHub CI reports failing checks"],
            "provenance": "github_ci_preflight",
        }
        followups = self.followups(job, result)
        result["recovery"] = {
            "automatic": bool(followups),
            "attempt": job["payload"].get("recovery_attempt", 0),
            "limit": self.settings.max_remediation_attempts,
            "next": "remediation" if followups else None,
        }
        body = (
            "GitHub checks failed before starting a paid independent validator. No runtime evidence or passing gate is claimed.\n\n"
            + "\n".join(
                f"- {c['name']}: {c.get('conclusion') or c['status']}" for c in ci["checks"]
            )
            + (
                "\n\nDevin remediation is queued automatically on this PR."
                if followups
                else "\n\nAutomatic remediation is disabled or its bounded attempts are exhausted."
            )
        )
        publication = PublicationOutbox(self.settings, self.store, self.providers).prepare_github(
            job["id"],
            job["pr_number"],
            body,
            validation={
                "job_id": job["id"],
                "targets": [{"number": job["pr_number"], "sha": job["candidate_sha"]}],
                "revision": "ci-preflight",
            },
        )
        self.store.commit_validation(
            job["id"], "validation_failed", result, result["blocker"], [publication], followups
        )
        return False

    def preflight(self, job):
        try:
            pr = current_pr(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
            if pr["head"]["ref"] != job["payload"]["head_ref"]:
                raise ValueError("Remediation branch changed")
        except ValueError as error:
            self.store.update(job["id"], state="stale", error=str(error))
            return False
        if key := job["payload"].get("failure_publication_key"):
            if not any(
                p["key"] == key and p["state"] == "sent" for p in self.store.all_publications()
            ):
                self.store.update(
                    job["id"], error="Waiting for failed-validation report delivery to be confirmed"
                )
                return False
            self.store.update(job["id"], error=None)
        return True

    def finish(self, job, result):
        if result.get("task_complete") is not True or result.get("blocker"):
            self.store.update(
                job["id"],
                state="needs_attention",
                result=result,
                error="Devin remediation is incomplete: " + str(result.get("blocker", ""))[:250],
            )
            return
        pr = self.providers.pr(job["pr_number"])
        sha = pr["head"]["sha"]
        current_pr(self.settings, self.providers, job["pr_number"], sha)
        if (
            pr["head"]["ref"] != job["payload"]["head_ref"]
            or result.get("candidate_sha") != sha
            or result.get("pr_url")
            != f"https://github.com/{self.settings.repo}/pull/{job['pr_number']}"
        ):
            raise ValueError("Remediation must preserve the original PR branch and observed SHA")
        if sha == job["candidate_sha"]:
            ci = ci_status(self.settings, self.providers, job["pr_number"], sha)
            if (
                result.get("metadata_only") is not True
                or ci["state"] != "success"
                or (job["payload"].get("failure_context", {}).get("ci") or {}).get("state")
                != "failure"
            ):
                raise ValueError(
                    "Unchanged SHA requires explicit metadata-only remediation and newly passing CI"
                )
        payload = {
            **job["payload"],
            "implementation_jobs": list(
                dict.fromkeys([*job["payload"].get("implementation_jobs", []), job["id"]])
            ),
            "source": "automatic_remediation_handoff",
            "work_type": "remediation",
        }
        publication = PublicationOutbox(self.settings, self.store, self.providers).prepare_github(
            job["id"],
            job["pr_number"],
            f"Devin automatically repaired this PR; its final candidate is `{sha}`.\n\n"
            f"Implementation session: {job['session_url']}\n\nFresh independent validation is queued. "
            "Earlier screenshots and checks do not approve this new revision. "
            "This reply is delivered by the configured GitHub integration.",
        )
        self.store.commit_handoff(
            job["id"],
            values={"state": "prepared", "candidate_sha": sha, "result": result},
            followups=[
                {
                    "key": f"validation:{self.settings.repo}:{job['pr_number']}:{sha}:after:{job['id']}",
                    "kind": "validation",
                    "payload": payload,
                    "parent_id": job["id"],
                    "candidate_sha": sha,
                    "pr_number": job["pr_number"],
                }
            ],
            publications=[publication],
            supersede_candidates=[{"number": job["pr_number"], "sha": job["candidate_sha"]}],
        )

    def reconcile(self):
        """Recover old failed gates and observe CI after evidence has completed."""
        from .validation import ValidationService

        validator = ValidationService(self.settings, self.store, self.providers)
        jobs = self.store.operational_jobs()
        for job in jobs:
            if job["kind"] != "validation" or job["state"] not in {
                "validation_failed",
                "review_ready",
                "awaiting_ci",
            }:
                continue
            if any(
                j["kind"] == "validation"
                and j["pr_number"] == job["pr_number"]
                and j["created"] > job["created"]
                and j["state"] != "stale"
                for j in jobs
            ):
                continue  # Only the latest gate may schedule follow-up work for a PR.
            if any(
                j["kind"] == "remediation"
                and j["pr_number"] == job["pr_number"]
                and j["state"]
                in {"queued", "running", "dispatching", "needs_attention", "unknown_effect"}
                for j in jobs
            ):
                continue
            if not validator.is_current(job):
                continue
            result = job.get("result") or {}
            if job["state"] == "validation_failed":
                followups = self.followups(job, result)
                if followups:
                    self.store.commit_handoff(
                        job["id"], values={"result": result}, followups=followups
                    )
                continue
            ci = ci_status(self.settings, self.providers, job["pr_number"], job["candidate_sha"])
            if ci == result.get("ci"):
                continue
            # Re-run the ordinary evidence gate and atomic publication path. Never manufacture proof.
            result = {
                k: v
                for k, v in result.items()
                if k not in {"gate", "gate_failures", "ci", "provenance"}
            }
            validator.finish_validation(job, result)
