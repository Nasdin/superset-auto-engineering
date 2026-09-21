"""Bounded autonomous correction of provider-confirmed idle final handoffs."""

import hashlib
import json
import time

from .providers import ProviderError, UnknownEffect


class HandoffRecovery:
    def __init__(self, engine):
        self.engine = engine
        self.store, self.providers, self.settings = engine.store, engine.providers, engine.settings

    @staticmethod
    def fingerprint(result):
        return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()

    def fresh_after_followup(self, job, session, result, previous):
        if not previous.get("attempts"):
            return True
        if self.fingerprint(result) != previous.get("original_handoff"):
            return True
        with self.store.connect() as connection:
            observations = connection.execute(
                "SELECT detail FROM audit WHERE job_id=:id AND kind='session_observed' AND created>:at",
                {"id": job["id"], "at": previous.get("requested_at", float("inf"))},
            ).fetchall()
        return any(
            json.loads(row["detail"]).get("detail") in {"working", "executing", "running"}
            for row in observations
        )

    def tick(self):
        for job in self.store.operational_jobs():
            if job["state"] != "needs_attention" or not job.get("session_id"):
                continue
            session = self.providers.session(job["session_id"])
            if session.get("session_id") != job[
                "session_id"
            ] or f"cognition-job:{job['id']}" not in session.get("tags", []):
                continue
            if (
                session.get("is_archived")
                or session.get("status") in {"error", "exit"}
                or (
                    session.get("status") == "suspended"
                    and session.get("status_detail") != "inactivity"
                )
            ):
                continue  # Credit, approval and live/unknown states are never released.
            if session.get("status_detail") not in {"finished", "waiting_for_user", "inactivity"}:
                continue
            result = session.get("structured_output")
            complete = isinstance(result, dict) and result.get("task_complete") is True
            key = f"handoff-followup:{job['id']}"
            previous = self.store.recall(key, {})
            if previous.get("attempts") and not self.fresh_after_followup(
                job, session, result, previous
            ):
                continue  # Message acknowledgement is not proof that its work completed.
            if complete and not result.get("blocker") and session.get("status") != "suspended":
                self.engine.poll(job)  # Ordinary checks and provenance still apply.
                if self.store.get(job["id"])["state"] != "needs_attention":
                    return
            if previous.get("attempts", 0) >= self.settings.max_handoff_followups:
                if (
                    session.get("status_detail") in {"finished", "waiting_for_user", "inactivity"}
                    and complete
                ):
                    # A conclusive failed task is terminal, not an indefinitely live executor.
                    self.store.update(
                        job["id"],
                        state="failed",
                        result=result,
                        error="Devin concluded with an unresolved blocker after bounded handoff recovery",
                    )
                    self.store.audit(
                        job["id"],
                        "terminal_handoff_failed",
                        {
                            "session_id": job["session_id"],
                            "provider_status": session.get("status"),
                            "provider_detail": session.get("status_detail"),
                            "task_complete": True,
                        },
                    )
                continue
            if job["kind"] in {"validation", "remediation"}:
                from .readiness import current_pr

                try:
                    current_pr(
                        self.settings, self.providers, job["pr_number"], job["candidate_sha"]
                    )
                except ValueError:
                    self.store.update(
                        job["id"], state="stale", error="Candidate changed before handoff follow-up"
                    )
                    continue
            now = time.time()
            intent = {
                "attempts": previous.get("attempts", 0) + 1,
                "state": "unknown_effect",
                "requested_at": now,
                "original_handoff": self.fingerprint(result),
            }
            with self.store.connect() as c:
                c.lock()
                changed = c.execute(
                    "UPDATE jobs SET state='unknown_effect',error='Automatic handoff clarification pending' WHERE id=:id AND state='needs_attention'",
                    {"id": job["id"]},
                ).rowcount
                if not changed:
                    continue
                c.execute(
                    "INSERT INTO memory VALUES(:key,:value,:now) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                    {
                        "key": key,
                        "value": json.dumps(
                            {"attempts": previous.get("attempts", 0) + 1, "state": "unknown_effect"}
                        ),
                        "now": now,
                    },
                )
            self.store.audit(
                job["id"],
                "automatic_handoff_requested",
                {"session_id": job["session_id"], "correlation": key},
            )
            try:
                response = self.providers.devin(
                    "POST",
                    f"sessions/{job['session_id']}/messages",
                    json={
                        "message": "The automated workflow cannot accept your final handoff. Resolve the precise remaining gaps within your original task, repository, branch and existing budget. "
                        "Preserve existing progress. Do not create child sessions, change budgets, merge, deploy, or weaken checks. "
                        "For a validator, do not edit or push code: collect the missing actual evidence. "
                        "Recheck your structured output. Set task_complete=true only after concluding; use an empty blocker only if there is truly no unresolved blocker. "
                        "Do not write 'None' plus caveats in blocker. If genuinely blocked, report a concrete blocker and conclude truthfully. "
                        "Share actual required artifacts with their provider URLs; never invent output. Include this correction correlation in your final summary so the worker can distinguish the new handoff. "
                        f"Recorded blocker: {str((result or {}).get('blocker', job.get('error', 'Missing final handoff')))[:1200] if isinstance(result, dict) else 'Missing final structured handoff'}. "
                        f"Automatic correlation: {key}."
                    },
                )
                if (
                    not isinstance(response, dict)
                    or response.get("session_id") != job["session_id"]
                ):
                    raise UnknownEffect("Automatic handoff response identity is unconfirmed")
                self.store.update(job["id"], state="running", error=None, next_poll=0, started=now)
                self.store.remember(key, {**intent, "state": "acknowledged"})
            except ProviderError as error:
                self.store.update(job["id"], state="needs_attention", error=str(error))
            except UnknownEffect as error:
                self.store.update(job["id"], state="unknown_effect", error=str(error))
            return  # At most one paid follow-up message per worker tick.
