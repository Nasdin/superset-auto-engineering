"""Durable report delivery: acknowledged writes retry readback, never resend."""

import uuid

from .config import Settings
from .links import safe_link
from .ports import ProviderGateway
from .providers import ProviderError, UnknownEffect
from .redaction import provider_secrets, redact_text
from .store import Store


class PublicationOutbox:
    def __init__(self, settings: Settings, store: Store, providers: ProviderGateway):
        self.settings = settings
        self.store = store
        self.providers = providers

    def publish(self, jid, number, body, validation=None):
        key = f"github:{jid}:{number}"
        self.store.queue_publication(
            key,
            {
                "provider": "github",
                "repository": self.settings.repo,
                "number": number,
                "body": f"<!-- {key} -->\n" + redact_text(body, provider_secrets(self.settings)),
                "validation": validation,
            },
        )

    def publish_slack(self, job, body, validation=None):
        key = f"slack:{job['id']}"
        self.store.queue_publication(
            key,
            {
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
        if not job or job["state"] not in {"review_ready", "validation_failed", "needs_attention"}:
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

    def flush_publication(self):
        item = self.store.claim_publication()
        if not item:
            return
        key, payload = item["key"], item["payload"]
        receipt = item.get("receipt")
        try:
            if not receipt:
                if payload.get("validation"):
                    try:
                        current = self.current_report(payload["validation"])
                    except ProviderError as error:
                        self.store.finish_publication(key, "pending", error=str(error))
                        return  # Read failed before a write: safe to retry verification.
                    if not current:
                        self.store.finish_publication(
                            key,
                            "stale",
                            error="PR changed before publication; previous evidence was not posted",
                        )
                        return
                if payload["provider"] == "github":
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
            url = self.providers.confirm_publication(payload, receipt)
            if not safe_link(url):
                raise ProviderError("Provider returned an invalid report URL")
            self.store.finish_publication(key, "sent", url=url)
        except (UnknownEffect, ProviderError, KeyError, TypeError, ValueError) as error:
            state = (
                "delivered"
                if receipt
                else "failed"
                if isinstance(error, ProviderError)
                else "unknown_effect"
            )
            self.store.finish_publication(key, state, error=str(error))
