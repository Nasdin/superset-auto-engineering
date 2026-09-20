"""Durable recovery policy. Retry observations, never an unacknowledged mutation."""

import random
import time

from .providers import ProviderError

MAX_ATTEMPTS = 5
BASE_SECONDS = 30
MAX_SECONDS = 1800
CREDIT_REASONS = {
    "usage_limit_exceeded",
    "out_of_credits",
    "out_of_quota",
    "no_quota_allocation",
    "payment_declined",
    "org_usage_limit_exceeded",
    "total_session_limit_exceeded",
}


def backoff(attempt, retry_after=0):
    delay = min(MAX_SECONDS, BASE_SECONDS * 2 ** min(attempt - 1, 10))
    return max(min(MAX_SECONDS, delay * random.uniform(1, 1.25)), min(86400, retry_after or 0))


class Recovery:
    def __init__(self, store):
        self.store = store

    def record(self, key):
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM recovery WHERE key=:key", {"key": key}).fetchone()
            return dict(row) if row else None

    def save(self, key, *, attempts, stage, category, next_retry, replay_state):
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO recovery VALUES(:key,:attempts,:stage,:category,:next_retry,:replay_state,:updated) "
                "ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts,stage=excluded.stage,"
                "category=excluded.category,next_retry=excluded.next_retry,replay_state=excluded.replay_state,updated=excluded.updated",
                dict(
                    key=key,
                    attempts=attempts,
                    stage=stage,
                    category=category,
                    next_retry=next_retry,
                    replay_state=replay_state,
                    updated=time.time(),
                ),
            )

    def clear(self, key):
        with self.store.connect() as c:
            c.execute("DELETE FROM recovery WHERE key=:key", {"key": key})

    def failure(self, key, error, stage, replay_state):
        prior = self.record(key) or {}
        category = getattr(error, "category", "invalid_result")
        held = category in {"credits", "authentication", "circuit_open", "local_limit"}
        attempts = prior.get("attempts", 0) + (0 if held else 1)
        transient = isinstance(error, ProviderError) and error.retryable
        exhausted = not held and (not transient or attempts >= MAX_ATTEMPTS)
        due = time.time() + backoff(max(1, attempts), getattr(error, "retry_after", 0))
        if category in {"credits", "authentication", "local_limit"}:
            state = "blocked"
        else:
            state = "dead_letter" if exhausted else replay_state
        self.save(
            key,
            attempts=attempts,
            stage=stage,
            category=category,
            next_retry=due,
            replay_state=replay_state,
        )
        return state, due

    def job_failure(self, job, error, stage="provider"):
        current = self.store.get(job["id"])
        if current["state"] in {"stale", "review_ready", "completed", "implemented", "integrated"}:
            return
        replay = "running" if current.get("session_id") else "queued"
        state, due = self.failure("job:" + job["id"], error, stage, replay)
        self.store.update(job["id"], state=state, next_poll=due, error=str(error))
        self.store.audit(
            job["id"], "recovery_scheduled", {"state": state, "stage": stage, "next_retry": due}
        )

    def publication_failure(self, key, error, receipt):
        replay = "delivered" if receipt else "pending"
        state, _ = self.failure(
            "publication:" + key, error, "confirmation" if receipt else "delivery", replay
        )
        self.store.finish_publication(key, state, error=str(error), receipt=receipt)

    def overview(self):
        worker = self.store.recall("worker_status", {})
        now = time.time()
        with self.store.connect() as c:
            records = {r["key"]: dict(r) for r in c.execute("SELECT * FROM recovery")}
            inbox = [
                {**dict(r), "recovery": records.get("inbox:" + r["id"])}
                for r in c.execute(
                    "SELECT id,state,error,next_retry,created,updated FROM github_inbox ORDER BY created DESC"
                )
            ]
        jobs = [
            {
                **{k: j.get(k) for k in ("id", "kind", "state", "error", "session_id")},
                "recovery": records.get("job:" + j["id"]),
            }
            for j in self.store.operational_jobs()
        ]
        publications = [
            {**p, "recovery": records.get("publication:" + p["key"])}
            for p in self.store.all_publications()
        ]
        breakers = [
            dict(
                provider=p, **self.store.recall("breaker:" + p, {"state": "closed", "failures": 0})
            )
            for p in ("devin", "github", "slack")
        ]
        rows = jobs + publications + inbox
        return {
            "worker": {**worker, "stale": now - worker.get("at", 0) > 180},
            "retry_policy": {
                "max_attempts": MAX_ATTEMPTS,
                "base_seconds": BASE_SECONDS,
                "max_seconds": MAX_SECONDS,
            },
            "breakers": breakers,
            "jobs": jobs,
            "publications": publications,
            "inbox": inbox,
            "durability": {
                "database": self.store.database.engine.dialect.name,
                "single_worker": True,
                "backups_enabled": False,
            },
            "counts": {
                "retrying": sum(
                    bool(r.get("recovery"))
                    and r["state"] in {"queued", "running", "pending", "delivered"}
                    for r in rows
                ),
                "dead_letters": sum(r["state"] == "dead_letter" for r in rows),
                "held": sum(r["state"] in {"blocked", "needs_attention"} for r in rows),
                "uncertain": sum(r["state"] == "unknown_effect" for r in rows),
                "pending_publications": sum(
                    p["state"] not in {"sent", "stale"} for p in publications
                ),
            },
        }
