"""Coordinate issue intake and bounded sessions; delegate integration and evidence."""

import hashlib
import re
import time

from .config import Settings
from .integration import IntegrationService
from .learning import LearningService
from .links import safe_link
from .outbox import PublicationOutbox
from .patches import preparation_service
from .ports import ProviderGateway
from .prompts import session_payload
from .providers import ProviderError, UnknownEffect
from .resilience import CREDIT_REASONS, Recovery
from .store import Store
from .validation import ValidationService


class Engine:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        settings.check_repo()
        store.bind_scope(settings.repo, settings.branch, settings.org)
        self.settings = settings
        self.store = store
        self.providers = providers
        if hasattr(providers, "store"):
            providers.store = store

    def accept_issue(self, number, source):
        prior = self.store.by_key(f"issue:{self.settings.repo}:{number}")
        if prior:
            return prior
        issue = self.providers.gh("GET", f"repos/{self.settings.repo}/issues/{number}")
        if issue.get("pull_request") or issue["state"] != "open":
            raise ValueError("Only open issues are eligible")
        if self.settings.label not in [x["name"] for x in issue.get("labels", [])]:
            raise ValueError("Required repair label is missing")
        if issue["user"]["login"].lower() != self.settings.allowed_actor.lower():
            raise ValueError("Issue author is not authorized")
        ref = self.providers.gh("GET", f"repos/{self.settings.repo}/commits/{self.settings.branch}")
        return self.store.enqueue(
            f"issue:{self.settings.repo}:{number}",
            "repair",
            {
                "issue_number": number,
                "title": issue["title"],
                "issue_url": issue["html_url"],
                "base_sha": ref["sha"],
                "source": source,
            },
        )

    def accept_webhook(self, issue_number: int, delivery_id: str):
        if self.store.has_delivery(delivery_id):
            return {"status": "duplicate"}
        job = self.accept_issue(issue_number, "github_webhook")
        self.store.record_delivery(delivery_id)
        return {"status": "accepted", "job_id": job["id"]}

    def poll_issues(self):
        page = self.store.recall("issue_poll_page", 1)
        issues = self.providers.gh(
            "GET",
            f"repos/{self.settings.repo}/issues",
            params={
                "state": "open",
                "labels": self.settings.label,
                "per_page": 50,
                "page": page,
                "sort": "created",
                "direction": "asc",
            },
        )
        accepted = 0
        for issue in issues:
            try:
                self.accept_issue(issue["number"], "github_poll")
                accepted += 1
            except ValueError:
                continue
        self.store.remember("last_issue_poll", {"at": time.time(), "eligible": accepted})
        self.store.remember("issue_poll_page", page + 1 if len(issues) == 50 else 1)
        return accepted

    def schedule_scan(self):
        from .schedules import ScheduleService

        return ScheduleService(self.settings, self.store, self.providers).tick()

    def schedule_automations(self):
        from .schedules import ScheduleService

        return ScheduleService(self.settings, self.store, self.providers).tick_all()

    def tick(self):
        if not self.settings.devin_key or not self.settings.github_token:
            self.store.remember(
                "worker_status", {"state": "configuration_required", "at": time.time()}
            )
            return None
        job = self.store.claim(allow_dispatch=self.settings.enabled)
        if not job:
            return None
        try:
            if job["state"] == "queued":
                self.dispatch(job)
            else:
                self.poll(job)
            if not self.store.get(job["id"]).get("error"):
                Recovery(self.store).clear("job:" + job["id"])
        except UnknownEffect as e:
            self.store.update(job["id"], state="unknown_effect", error=str(e))
            self.store.audit(job["id"], "unknown_effect", {"action": "provider mutation"})
        except ProviderError as e:
            Recovery(self.store).job_failure(job, e)
        except OSError:
            Recovery(self.store).job_failure(
                job, ProviderError("Evidence storage unavailable", category="storage"), "archive"
            )
        except (ValueError, KeyError, TypeError) as e:
            Recovery(self.store).job_failure(
                job,
                ProviderError(
                    f"Invalid provider result: {type(e).__name__}",
                    category="invalid_result",
                    retryable=False,
                ),
                "handoff",
            )
        finally:
            self.store.update(job["id"], lease_until=0)
        return self.store.get(job["id"])

    def dispatch(self, job):
        if job["kind"] == "integration":
            self.assemble_candidate(job)
            return
        if job["kind"] in {"dependency", "patch"} and not preparation_service(
            self.settings, self.store, self.providers, job["kind"]
        ).preflight(job):
            return
        if job["kind"] == "remediation":
            from .remediation import RemediationService

            if not RemediationService(self.settings, self.store, self.providers).preflight(job):
                return
        if job["kind"] == "validation":
            if not ValidationService(self.settings, self.store, self.providers).is_current(job):
                return
            from .remediation import RemediationService

            if not RemediationService(
                self.settings, self.store, self.providers
            ).preflight_validation(job):
                return
            if (
                job["payload"].get("work_type") == "dependency"
                and not self.settings.dependabot_enabled
            ):
                self.store.update(
                    job["id"], state="blocked", error="Dependabot automation is disabled"
                )
                return
        used = self.store.session_count(excluding=job["id"])
        required_slots = {
            "repair": 2,
            "remediation": 2,
            "dependency": 2,
            "patch": 2,
            "scan": 3,
            "validation": 1,
            "audit": 1,
            "maintenance": 2,
        }[job["kind"]]
        if used + required_slots > self.settings.max_sessions:
            Recovery(self.store).job_failure(
                job,
                ProviderError(
                    "Configured total session limit reached",
                    category="local_limit",
                    retryable=False,
                ),
                "dispatch",
            )
            return
        try:
            context = LearningService(self.settings, self.store, self.providers).context(job)
        except (ProviderError, UnknownEffect) as error:
            # Knowledge reconciliation happens before session creation: no paid effect exists.
            self.store.remember(
                "learning_sync", {"state": "attention", "error": str(error), "at": time.time()}
            )
            Recovery(self.store).job_failure(
                job,
                ProviderError("Waiting for Knowledge reconciliation", category="knowledge"),
                "knowledge",
            )
            return
        payload = session_payload(self.settings, job, context)
        knowledge_ids = [x["knowledge_id"] for x in context if x["knowledge_id"]]
        if knowledge_ids:
            payload["knowledge_ids"] = knowledge_ids
        self.store.update(job["id"], state="dispatching", started=time.time())
        self.store.audit(
            job["id"],
            "dispatch_started",
            {"kind": job["kind"], "max_acu": self.settings.max_acu},
        )
        session = self.providers.create_session(payload)
        if not session.get("session_id") or not safe_link(session.get("url", "")):
            raise UnknownEffect("Creation response missing session identity; reconcile by job tag")
        self.store.update(
            job["id"],
            state="running",
            session_id=session["session_id"],
            session_url=session["url"],
            started=time.time(),
            next_poll=time.time() + self.settings.poll_seconds,
        )
        self.store.audit(job["id"], "session_created", {"session_id": session["session_id"]})

    def poll(self, job):
        session = self.providers.session(job["session_id"])
        if session.get("session_id") != job["session_id"]:
            raise ValueError("Provider returned a different session")
        self.store.update(
            job["id"],
            acu=session.get("acus_consumed", 0),
            next_poll=time.time() + self.settings.poll_seconds,
            error=None,
        )
        self.store.audit(
            job["id"],
            "session_observed",
            {"status": session.get("status"), "detail": session.get("status_detail")},
        )
        result = session.get("structured_output")
        if session.get("status") == "suspended" and session.get("status_detail") in CREDIT_REASONS:
            self.store.remember(
                "breaker:devin",
                {"state": "open", "reason": "credits", "failures": 1, "retry_at": 0},
            )
        # Devin can idle awaiting another instruction after completing a task.
        # Only an explicit final handoff may enter the normal evidence checks.
        ready = session.get("status_detail") == "finished" or (
            session.get("status") == "running"
            and session.get("status_detail") == "waiting_for_user"
            and isinstance(result, dict)
            and result.get("task_complete") is True
        )
        if ready:
            from .handoffs import HandoffRecovery

            followup = self.store.recall(f"handoff-followup:{job['id']}", {})
            if followup.get("attempts") and not HandoffRecovery(self).fresh_after_followup(
                job, session, result, followup
            ):
                return  # A message acknowledgement cannot replay the old completed handoff.
            if not isinstance(result, dict):
                raise ValueError("Finished session has no structured output")
            if job["kind"] == "repair":
                self.finish_repair(job, result)
            elif job["kind"] == "remediation":
                from .remediation import RemediationService

                RemediationService(self.settings, self.store, self.providers).finish(job, result)
            elif job["kind"] in {"dependency", "patch"}:
                preparation_service(self.settings, self.store, self.providers, job["kind"]).finish(
                    job, result
                )
            elif job["kind"] == "scan":
                self.finish_scan(job, result)
            elif job["kind"] == "maintenance":
                from .maintenance import finish_maintenance

                finish_maintenance(self.settings, self.store, self.providers, job, result)
            elif job["kind"] == "audit":
                from .reviews import finish_review

                finish_review(self.store, job, result)
            else:
                self.finish_validation(job, result)
            return
        if session.get("status") in {"error", "exit", "suspended"} or session.get(
            "status_detail"
        ) in {"waiting_for_user", "waiting_for_approval"}:
            self.store.update(
                job["id"],
                state="needs_attention",
                error=(
                    "Devin paused at its per-message/session spending limit. This does not establish that organization credits are exhausted. Open this session's usage limits, then resume the same session if work remains."
                    if session.get("status_detail")
                    in {"usage_limit_exceeded", "total_session_limit_exceeded"}
                    else f"Devin {session.get('status')}: {session.get('status_detail')}"
                ),
            )
        elif time.time() - (job.get("started") or time.time()) > self.settings.session_timeout:
            # Archive is a real provider action; an ambiguous result is never called stopped.
            self.providers.devin("POST", f"sessions/{job['session_id']}/archive", json={})
            self.store.update(
                job["id"],
                state="needs_attention",
                error="Time limit reached; archive requested. Inspect the provider session before resuming.",
            )

    def finish_repair(self, job, result):
        if result.get("blocker"):
            self.store.update(
                job["id"],
                state="needs_attention",
                error="Repair blocker: " + str(result["blocker"])[:250],
            )
            return
        pattern = rf"https://github\.com/{re.escape(self.settings.repo)}/pull/(\d+)"
        match = re.fullmatch(pattern, result.get("pr_url", ""), flags=re.I)
        if not match:
            self.store.update(
                job["id"],
                state="needs_attention",
                error="No PR in the configured fork: " + result.get("blocker", "")[:250],
            )
            return
        number = int(match[1])
        pr = self.providers.pr(number)
        if (
            pr["base"]["repo"]["full_name"].lower() != self.settings.repo.lower()
            or pr["base"]["ref"] != self.settings.branch
            or pr["state"] != "open"
        ):
            raise ValueError("PR target or state mismatch")
        sha = pr["head"]["sha"]
        publication = PublicationOutbox(self.settings, self.store, self.providers).prepare_github(
            job["id"],
            job["payload"]["issue_number"],
            f"Implementation prepared: {pr['html_url']}\n\nDevin session: {job['session_url']}\n\nCandidate `{sha}` is waiting for the integration batch and independent validation. It is not yet verified.",
        )
        self.store.commit_handoff(
            job["id"],
            values={
                "state": "implemented",
                "pr_number": number,
                "candidate_sha": sha,
                "result": result,
            },
            publications=[publication],
        )

    def finish_scan(self, job, result):
        from .scans import ScanResult

        handoff = ScanResult.model_validate(result)
        if not handoff.task_complete or handoff.blocker:
            self.store.update(
                job["id"],
                state="needs_attention",
                result=result,
                error=handoff.blocker or "Scan is not complete",
            )
            return
        findings = [finding.model_dump() for finding in handoff.findings]
        if len(findings) > 1:
            raise ValueError("Discovery exceeded one-issue scope")
        for finding in findings:
            if finding.get("base_sha") != job["payload"]["base_sha"] or not finding.get(
                "reproduction"
            ):
                raise ValueError("Discovery lacks baseline reproduction")
            fingerprint = hashlib.sha256(
                (self.settings.repo + finding["title"]).encode()
            ).hexdigest()[:20]
            key = "finding:" + fingerprint
            if previous := self.store.recall(key):
                child = self.accept_issue(previous["issue"], "scheduled_scan")
                if not child["parent_id"]:
                    self.store.update(child["id"], parent_id=job["id"])
                continue
            marker = f"<!-- cognition-finding:{fingerprint} -->"
            body = f"{marker}\n\n{finding['description']}\n\n## Reproduction at `{finding['base_sha']}`\n{finding['reproduction']}\n\n## Acceptance criteria\n{finding['acceptance']}\n\nDiscovered by {job['session_url']}. This is a reported finding; independent validation is required."
            # Reconcile previously uncertain issue creation by marker before any retry.
            prior = self.providers.gh(
                "GET",
                f"repos/{self.settings.repo}/issues",
                params={"state": "all", "per_page": 100},
            )
            issue = next((x for x in prior if marker in (x.get("body") or "")), None)
            if not issue:
                issue = self.providers.gh(
                    "POST",
                    f"repos/{self.settings.repo}/issues",
                    json={
                        "title": finding["title"],
                        "body": body,
                        "labels": [self.settings.label],
                    },
                )
            self.store.remember(key, {"issue": issue["number"], "sha": finding["base_sha"]})
            child = self.accept_issue(issue["number"], "scheduled_scan")
            self.store.update(child["id"], parent_id=job["id"])
        self.store.update(job["id"], state="completed", result=result)
        self.store.remember(
            "last_scan",
            {"job": job["id"], "findings": len(findings), "at": time.time()},
        )

    def finish_validation(self, job, result):
        return ValidationService(self.settings, self.store, self.providers).finish_validation(
            job, result
        )

    def publish(self, jid, number, body):
        return PublicationOutbox(self.settings, self.store, self.providers).publish(
            jid, number, body
        )

    def publish_slack(self, job, body):
        return PublicationOutbox(self.settings, self.store, self.providers).publish_slack(job, body)

    def flush_publication(self):
        return PublicationOutbox(self.settings, self.store, self.providers).flush_publication()

    def refresh_readiness(self):
        return ValidationService(self.settings, self.store, self.providers).refresh_readiness()

    def schedule_batch(self):
        return IntegrationService(self.settings, self.store, self.providers).schedule_batch()

    def assemble_candidate(self, job):
        return IntegrationService(self.settings, self.store, self.providers).assemble_candidate(job)
