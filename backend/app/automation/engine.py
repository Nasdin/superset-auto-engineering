"""Coordinate issue intake and bounded sessions; delegate integration and evidence."""

import hashlib
import re
import time

from .config import Settings
from .dependencies import DependencyService
from .integration import IntegrationService
from .links import safe_link
from .outbox import PublicationOutbox
from .ports import ProviderGateway
from .prompts import session_payload
from .providers import ProviderError, UnknownEffect
from .store import Store
from .validation import ValidationService


class Engine:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        settings.check_repo()
        store.bind_scope(settings.repo, settings.branch, settings.org)
        self.settings = settings
        self.store = store
        self.providers = providers

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
        issues = self.providers.gh(
            "GET",
            f"repos/{self.settings.repo}/issues",
            params={"state": "open", "labels": self.settings.label, "per_page": 50},
        )
        accepted = 0
        for issue in issues:
            try:
                self.accept_issue(issue["number"], "github_poll")
                accepted += 1
            except ValueError:
                continue
        self.store.remember("last_issue_poll", {"at": time.time(), "eligible": accepted})
        return accepted

    def schedule_scan(self):
        bucket = int(time.time() // max(self.settings.scan_interval, 1))
        key = f"scan:{self.settings.repo}:{self.settings.branch}:{bucket}"
        prior = self.store.by_key(key)
        if prior:
            return prior
        ref = self.providers.gh("GET", f"repos/{self.settings.repo}/commits/{self.settings.branch}")
        return self.store.enqueue(
            key,
            "scan",
            {
                "base_sha": ref["sha"],
                "source": "schedule",
                "title": "Scheduled bounded correctness scan",
            },
        )

    def tick(self):
        if not self.settings.enabled:
            return None
        if not self.settings.devin_key or not self.settings.github_token:
            self.store.remember(
                "worker_status", {"state": "configuration_required", "at": time.time()}
            )
            return None
        job = self.store.claim()
        if not job:
            return None
        try:
            if job["state"] == "queued":
                self.dispatch(job)
            else:
                self.poll(job)
        except UnknownEffect as e:
            self.store.update(job["id"], state="unknown_effect", error=str(e))
            self.store.audit(job["id"], "unknown_effect", {"action": "provider mutation"})
        except ProviderError as e:
            # Poll errors are observations, not terminal session status.
            self.store.update(
                job["id"], error=str(e), next_poll=time.time() + self.settings.poll_seconds
            )
            if job["state"] == "queued":
                self.store.update(job["id"], state="blocked")
        except (ValueError, KeyError, TypeError) as e:
            self.store.update(
                job["id"],
                state="needs_attention",
                error=f"Invalid provider result: {type(e).__name__}: {str(e)[:250]}",
            )
        finally:
            self.store.update(job["id"], lease_until=0)
        return self.store.get(job["id"])

    def dispatch(self, job):
        if job["kind"] == "integration":
            self.assemble_candidate(job)
            return
        if job["kind"] == "dependency" and not DependencyService(
            self.settings, self.store, self.providers
        ).preflight(job):
            return
        if job["kind"] == "validation" and job["payload"].get("work_type") == "dependency":
            if not ValidationService(self.settings, self.store, self.providers).is_current(job):
                return
            if not self.settings.dependabot_enabled:
                self.store.update(
                    job["id"], state="blocked", error="Dependabot automation is disabled"
                )
                return
        used = self.store.session_count(excluding=job["id"])
        required_slots = {"repair": 2, "dependency": 2, "scan": 3, "validation": 1}[job["kind"]]
        if used + required_slots > self.settings.max_sessions:
            self.store.update(
                job["id"],
                state="blocked",
                error="Configured total session limit reached",
            )
            return
        payload = session_payload(self.settings, job, self.store.recall("repository_lessons", []))
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
        # Devin can idle awaiting another instruction after completing a task.
        # Only an explicit final handoff may enter the normal evidence checks.
        ready = session.get("status_detail") == "finished" or (
            session.get("status") == "running"
            and session.get("status_detail") == "waiting_for_user"
            and isinstance(result, dict)
            and result.get("task_complete") is True
        )
        if ready:
            if not isinstance(result, dict):
                raise ValueError("Finished session has no structured output")
            if job["kind"] == "repair":
                self.finish_repair(job, result)
            elif job["kind"] == "dependency":
                DependencyService(self.settings, self.store, self.providers).finish(job, result)
            elif job["kind"] == "scan":
                self.finish_scan(job, result)
            else:
                self.finish_validation(job, result)
            return
        if session.get("status") in {"error", "exit", "suspended"} or session.get(
            "status_detail"
        ) in {"waiting_for_user", "waiting_for_approval"}:
            self.store.update(
                job["id"],
                state="needs_attention",
                error=f"Devin {session.get('status')}: {session.get('status_detail')}",
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
        self.publish(
            job["id"],
            job["payload"]["issue_number"],
            f"Implementation prepared: {pr['html_url']}\n\nDevin session: {job['session_url']}\n\nCandidate `{sha}` is waiting for the integration batch and independent validation. It is not yet verified.",
        )
        self.store.update(
            job["id"],
            state="implemented",
            pr_number=number,
            candidate_sha=sha,
            result=result,
        )

    def finish_scan(self, job, result):
        findings = result.get("findings", [])
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
            if self.store.recall(key):
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
            self.accept_issue(issue["number"], "scheduled_scan")
        self.store.update(job["id"], state="completed")
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
