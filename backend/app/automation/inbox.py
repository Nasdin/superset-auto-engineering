"""Acknowledge signed GitHub events only after durable storage, before provider reads."""

import json
import time
import uuid

from .dependencies import DependencyService
from .patches import PatchService
from .pr_validation import VALIDATE_LABEL, PullRequestValidationService
from .providers import ProviderError, UnknownEffect
from .resilience import Recovery


class Inbox:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store

    def accept(self, delivery_id, payload):
        """The route has already authenticated and normalized this minimal event."""
        now = time.time()
        with self.store.connect() as c:
            inserted = c.execute(
                "INSERT INTO github_inbox(id,payload,state,created,updated) "
                "VALUES(:id,:payload,'pending',:now,:now) ON CONFLICT DO NOTHING",
                {"id": delivery_id, "payload": json.dumps(payload), "now": now},
            ).rowcount
        return {"status": "queued" if inserted else "duplicate", "delivery_id": delivery_id}

    def claim(self):
        now, token = time.time(), str(uuid.uuid4())
        with self.store.connect() as c:
            c.lock()
            row = c.execute(
                "SELECT * FROM github_inbox WHERE "
                "(state='pending' AND next_retry<=:now) OR "
                "(state='processing' AND lease_until<:now) ORDER BY created LIMIT 1",
                {"now": now},
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE github_inbox SET state='processing',lease_token=:token,"
                "lease_until=:lease,updated=:now WHERE id=:id",
                {"token": token, "lease": now + 180, "now": now, "id": row["id"]},
            )
            return {**dict(row), "payload": json.loads(row["payload"]), "lease_token": token}

    def process(self, item):
        # All provider operations here are reads. Existing intake methods perform
        # idempotent local ledger changes; reclaiming an interrupted intake is safe.
        eng, payload, delivery = self.engine, item["payload"], item["id"]
        if eng.store.has_delivery(delivery):
            return {"status": "duplicate"}
        number = payload["number"]
        if payload["event"] == "issues":
            return eng.accept_webhook(number, delivery)
        pr = eng.providers.pr(number)
        if VALIDATE_LABEL in [x.get("name") for x in pr.get("labels", [])] or any(
            j["pr_number"] == number and j["kind"] in {"repair", "integration"}
            for j in eng.store.operational_jobs()
        ):
            job = PullRequestValidationService(eng.settings, eng.store, eng.providers).accept(
                number, "pr_validation_webhook", payload["sha"]
            )
            eng.store.record_delivery(delivery)
            return {
                "status": job.get("status", "accepted"),
                "job_id": job.get("id"),
                "reason": job.get("reason"),
            }
        service = (
            PatchService
            if pr.get("user", {}).get("login", "").lower() == eng.settings.allowed_actor.lower()
            else DependencyService
        )(eng.settings, eng.store, eng.providers)
        return service.webhook(number, delivery, payload["sha"])

    def tick(self):
        item = self.claim()
        if not item:
            return None
        key = "inbox:" + item["id"]
        recovery = Recovery(self.store)
        result, error, due = None, None, 0
        try:
            result = self.process(item)
            state = "ignored" if result.get("status") == "ignored" else "completed"
            recovery.clear(key)
        except ProviderError as failure:
            state, due = recovery.failure(key, failure, "intake", "pending")
            error = str(failure)
        except UnknownEffect as failure:
            state, error = "unknown_effect", str(failure)
        except ValueError as failure:
            state, error = "ignored", str(failure)
        except (KeyError, TypeError) as failure:
            state, due = recovery.failure(key, failure, "intake", "pending")
            error = "Invalid intake result: " + type(failure).__name__
        with self.store.connect() as c:
            changed = c.execute(
                "UPDATE github_inbox SET state=:state,result=:result,error=:error,"
                "next_retry=:due,lease_until=0,lease_token=NULL,updated=:now "
                "WHERE id=:id AND lease_token=:token",
                {
                    "id": item["id"],
                    "token": item["lease_token"],
                    "state": state,
                    "result": json.dumps(result) if result else None,
                    "error": error,
                    "due": due,
                    "now": time.time(),
                },
            ).rowcount
        return {"delivery_id": item["id"], "state": state, "result": result} if changed else None

    def overview(self):
        """Operational metadata only; no raw webhook body or provider credentials."""
        with self.store.connect() as c:
            return [
                dict(row)
                for row in c.execute(
                    "SELECT id,state,error,next_retry,created,updated FROM github_inbox "
                    "ORDER BY created DESC LIMIT 100"
                )
            ]
