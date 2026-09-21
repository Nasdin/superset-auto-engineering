"""Durable report delivery: acknowledged writes retry readback, never resend."""

import uuid

from .config import Settings
from .links import safe_link
from .ports import ProviderGateway
from .providers import ProviderError, UnknownEffect
from .redaction import provider_secrets, redact_text
from .resilience import Recovery
from .store import Store


class PublicationOutbox:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        self.settings = settings
        self.store = store
        self.providers = providers

    def publish(self, jid, number, body, validation=None):
        self.store.queue_publication(**self.prepare_github(jid, number, body, validation))

    def prepare_github(self, jid, number, body, validation=None):
        key = f"github:{jid}:{number}"
        if validation and validation.get("revision"):
            key += ":" + validation["revision"]
        return dict(
            key=key,
            payload={
                "provider": "github",
                "repository": self.settings.repo,
                "number": number,
                "body": f"<!-- {key} -->\n" + redact_text(body, provider_secrets(self.settings)),
                "validation": validation,
            },
        )

    def prepare_ready(self, job, revision="initial"):
        return {
            "key": f"github-ready:{job['id']}:{job['candidate_sha']}:{revision}",
            "payload": {
                "provider": "github_ready",
                "repository": self.settings.repo,
                "number": job["pr_number"],
                "sha": job["candidate_sha"],
                "validation": {
                    "job_id": job["id"],
                    "targets": [{"number": job["pr_number"], "sha": job["candidate_sha"]}],
                },
            },
        }

    def publish_slack(self, job, body, validation=None):
        self.store.queue_publication(**self.prepare_slack(job, body, validation))

    def prepare_slack(self, job, body, validation=None):
        key = f"slack:{job['id']}"
        if validation and validation.get("revision"):
            key += ":" + validation["revision"]
        return dict(
            key=key,
            payload={
                "provider": "slack",
                "channel": self.settings.slack_channel,
                "body": f"Cognition {self.settings.repo} PR #{job['pr_number']}\n{redact_text(body, provider_secrets(self.settings))}",
                "validation": validation,
            },
        )

    def current_report(self, metadata):
        from .validation import ValidationService

        job = self.store.get(metadata["job_id"])
        if job and job["state"] in {"running", "dispatching"}:
            raise ProviderError("Validation handoff is still being committed")
        if not job or job["state"] not in {
            "review_ready",
            "validation_failed",
            "needs_attention",
            "awaiting_ci",
        }:
            return False
        if not ValidationService(self.settings, self.store, self.providers).is_current(job):
            return False
        for target in metadata.get("targets", []):
            pr = self.providers.pr(target["number"])
            if (
                pr["state"] != "open"
                or pr["head"]["sha"] != target["sha"]
                or pr["base"]["repo"]["full_name"].lower() != self.settings.repo.lower()
                or pr["base"]["ref"] != self.settings.branch
            ):
                return False
        return True

    def reconcile_readiness(self):
        """Resolve uncertain ready mutations only from observed state; never resend."""
        from .readiness import ci_status, current_pr

        with self.store.connect() as connection:
            items = [
                self.store.decode(row)
                for row in connection.execute(
                    "SELECT * FROM publications WHERE state='unknown_effect'"
                )
            ]
        for item in items:
            payload = item.get("payload") or {}
            if item["state"] != "unknown_effect" or payload.get("provider") != "github_ready":
                continue
            try:
                pr = current_pr(self.settings, self.providers, payload["number"], payload["sha"])
            except ValueError:
                self.store.finish_publication(
                    item["key"], "stale", error="Candidate changed during readiness reconciliation"
                )
                continue
            job = self.store.get(payload["validation"]["job_id"])
            if (
                pr.get("draft") is False
                and job
                and job["state"] == "review_ready"
                and ci_status(self.settings, self.providers, payload["number"], payload["sha"])[
                    "state"
                ]
                == "success"
            ):
                self.store.finish_publication(
                    item["key"],
                    "sent",
                    url=pr["html_url"],
                    receipt={
                        "number": payload["number"],
                        "sha": payload["sha"],
                        "reconciled": True,
                    },
                )
                self.store.audit(job["id"], "readiness_reconciled", {"sha": payload["sha"]})

    def flush_publication(self):
        item = self.store.claim_publication()
        if not item:
            return
        key, payload = item["key"], item["payload"]
        receipt = item.get("receipt")
        try:
            if not receipt:
                if payload.get("activity"):
                    from .activity import ValidationActivityService

                    if not ValidationActivityService(
                        self.settings, self.store, self.providers
                    ).current(payload["activity"]):
                        self.store.finish_publication(
                            key,
                            "stale",
                            error="Validation progress changed before activity delivery",
                        )
                        return
                if payload.get("validation"):
                    try:
                        current = self.current_report(payload["validation"])
                    except ProviderError:
                        raise  # Verification failed before a write: bounded safe retry.
                    if not current:
                        self.store.finish_publication(
                            key,
                            "stale",
                            error="PR changed before publication; previous evidence was not posted",
                        )
                        return
                if payload["provider"] == "github_ready":
                    from .readiness import ci_status

                    job = self.store.get(payload["validation"]["job_id"])
                    if job["state"] != "review_ready":
                        self.store.finish_publication(
                            key, "stale", error="Release gate is not ready"
                        )
                        return
                    ci = ci_status(self.settings, self.providers, payload["number"], payload["sha"])
                    if ci["state"] != "success":
                        self.store.finish_publication(
                            key, "stale", error="CI changed before readiness publication"
                        )
                        return
                    receipt = self.providers.mark_ready(payload["number"], payload["sha"])
                elif payload["provider"] == "github":
                    result = self.providers.comment(
                        payload["number"],
                        payload["body"],
                        repository=payload.get("repository", self.settings.repo),
                    )
                    receipt = {"id": result["id"]}
                else:
                    result = self.providers.slack(
                        payload["body"],
                        str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                        channel=payload.get("channel", self.settings.slack_channel),
                    )
                    receipt = {"channel": result["channel"], "ts": result["ts"]}
                # Persist the acknowledged write BEFORE any readback. If the read
                # fails or the worker crashes, only confirmation is retried.
                self.store.finish_publication(key, "confirming", receipt=receipt)
            if payload["provider"] == "github_ready":
                from .readiness import current_pr

                pr = current_pr(self.settings, self.providers, payload["number"], payload["sha"])
                if pr.get("draft") is not False:
                    raise ProviderError("PR readiness mutation has not been confirmed")
                url = pr["html_url"]
            else:
                url = self.providers.confirm_publication(payload, receipt)
            if not safe_link(url):
                raise ProviderError("Provider returned an invalid report URL")
            self.store.finish_publication(key, "sent", url=url)
            Recovery(self.store).clear("publication:" + key)
        except (UnknownEffect, ProviderError, KeyError, TypeError, ValueError) as error:
            if not receipt and not isinstance(error, ProviderError):
                self.store.finish_publication(key, "unknown_effect", error=str(error))
            else:
                Recovery(self.store).publication_failure(key, error, receipt)
