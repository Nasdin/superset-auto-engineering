"""Durable, bounded discovery scheduling; manual intent is distinct from recurrence."""

import json
import time
import uuid

from .catalogue import RECIPES, attributed_jobs, configuration_blocker, recipe_for


class ScheduleConflict(ValueError):
    pass


class ScheduleService:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    def schedule(self, automation_id="discovery"):
        recipe = recipe_for(automation_id)
        now = time.time()
        interval = (
            (self.settings.scan_interval or 86400)
            if automation_id == "discovery"
            else recipe.interval
        )
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO schedules(id,name,enabled,interval_seconds,next_run,updated) "
                "VALUES(:id,:name,:enabled,:interval,:due,:now) "
                "ON CONFLICT DO NOTHING",
                {
                    "id": automation_id,
                    "name": recipe.name,
                    "enabled": int(
                        automation_id == "discovery" and self.settings.scan_interval > 0
                    ),
                    "interval": interval,
                    "due": int(now // interval) * interval,
                    "now": now,
                },
            )
            return dict(
                c.execute("SELECT * FROM schedules WHERE id=:id", {"id": automation_id}).fetchone()
            )

    def configure(self, enabled, interval, expected_updated, automation_id="discovery"):
        self.schedule(automation_id)
        if enabled and (blocker := configuration_blocker(automation_id, self.settings)):
            raise ValueError(blocker)
        if interval not in {3600, 21600, 86400, 604800}:
            raise ValueError("Choose hourly, six-hourly, daily or weekly")
        now = time.time()
        with self.store.connect() as c:
            c.lock()
            row = c.execute(
                "SELECT * FROM schedules WHERE id=:id", {"id": automation_id}
            ).fetchone()
            if row["updated"] != expected_updated:
                raise ScheduleConflict("Schedule changed; refresh before saving")
            # Editing a recurrence never creates an immediate surprise paid run.
            due = now + interval if enabled else row["next_run"]
            c.execute(
                "UPDATE schedules SET enabled=:enabled,interval_seconds=:interval,"
                "next_run=:due,updated=:now WHERE id=:id",
                {
                    "id": automation_id,
                    "enabled": int(enabled),
                    "interval": interval,
                    "due": due,
                    "now": now,
                },
            )
        self.store.audit(
            None,
            "schedule_configured",
            {"automation_id": automation_id, "enabled": enabled, "interval": interval},
        )
        return self.schedule(automation_id)

    def _insert(self, c, key, sha, source, now, automation_id="discovery"):
        recipe = recipe_for(automation_id)
        c.execute(
            "INSERT INTO jobs(id,dedup,kind,state,payload,created,updated) "
            "VALUES(:id,:key,:kind,'queued',:payload,:now,:now) ON CONFLICT DO NOTHING",
            {
                "id": str(uuid.uuid4()),
                "key": key,
                "kind": recipe.kind,
                "now": now,
                "payload": json.dumps(
                    {
                        "base_sha": sha,
                        "source": source,
                        "title": recipe.name,
                        "automation_id": automation_id,
                        "schedule_id": automation_id if source == "schedule" else None,
                    }
                ),
            },
        )
        return self.store.decode(
            c.execute("SELECT * FROM jobs WHERE dedup=:key", {"key": key}).fetchone()
        )

    def _revision(self):
        return self.providers.gh(
            "GET", f"repos/{self.settings.repo}/commits/{self.settings.branch}"
        )["sha"]

    def _active(self, c, automation_id):
        rows = c.execute(
            "SELECT * FROM jobs WHERE kind IN ('scan','audit','maintenance') AND state IN "
            "('queued','dispatching','running','needs_attention','unknown_effect','blocked','dead_letter','prepared') ORDER BY created"
        )
        return next(
            (
                row
                for row in rows
                if (json.loads(row["payload"]).get("automation_id") or "discovery") == automation_id
            ),
            None,
        )

    def _reconcile_maintenance(self, automation_id):
        """Read GitHub outside a transaction; an open fix owns its recipe until closed."""
        if recipe_for(automation_id).kind != "maintenance":
            return
        for job in self.store.operational_jobs():
            if (
                job["kind"] != "maintenance"
                or job["state"] != "prepared"
                or job["payload"].get("automation_id") != automation_id
            ):
                continue
            pr = self.providers.pr(job["pr_number"])
            if pr.get("state") == "closed":
                with self.store.connect() as c:
                    c.lock()
                    c.execute(
                        "UPDATE jobs SET state='completed',updated=:now WHERE id=:id AND state='prepared'",
                        {"id": job["id"], "now": time.time()},
                    )

    def _completed_revision(self, c, automation_id, sha):
        if recipe_for(automation_id).kind != "maintenance":
            return None
        return next(
            (
                row
                for row in c.execute(
                    "SELECT * FROM jobs WHERE kind='maintenance' AND state='completed' ORDER BY created DESC"
                )
                if (payload := json.loads(row["payload"])).get("automation_id") == automation_id
                and payload.get("base_sha") == sha
            ),
            None,
        )

    def tick_all(self):
        # One recipe's outage must not hide the other durable schedules.
        results, failures = [], []
        for identity in RECIPES:
            try:
                results.append(self.tick(identity))
                self.store.remember("schedule_error:" + identity, None)
            except Exception as error:
                failures.append(identity)
                self.store.remember(
                    "schedule_error:" + identity, {"error": type(error).__name__, "at": time.time()}
                )
        if failures:
            raise ScheduleConflict("Scheduler checks failed: " + ", ".join(failures))
        return results

    def tick(self, automation_id="discovery"):
        row = self.schedule(automation_id)
        now = time.time()
        if not row["enabled"] or row["next_run"] > now:
            return self.store.get(row["last_job_id"]) if row["last_job_id"] else None
        if blocker := configuration_blocker(automation_id, self.settings):
            raise ScheduleConflict(blocker)
        self._reconcile_maintenance(automation_id)
        sha = self._revision()
        with self.store.connect() as c:
            c.lock()
            current = c.execute(
                "SELECT * FROM schedules WHERE id=:id", {"id": automation_id}
            ).fetchone()
            if not current["enabled"] or current["next_run"] > now:
                return None
            # Coalesce missed ticks; never replay a backlog of paid scans after downtime.
            active = self._active(c, automation_id) or self._completed_revision(
                c, automation_id, sha
            )
            if active:
                c.execute(
                    "UPDATE schedules SET next_run=:due,last_job_id=:job WHERE id=:id",
                    {
                        "id": automation_id,
                        "due": now + current["interval_seconds"],
                        "job": active["id"],
                    },
                )
                return self.store.decode(active)
            interval = current["interval_seconds"]
            bucket = int(now // interval)
            key = (
                f"scan:{self.settings.repo}:{self.settings.branch}:{bucket}"
                if automation_id == "discovery"
                else f"automation:{automation_id}:{self.settings.repo}:{bucket}"
            )
            job = self._insert(c, key, sha, "schedule", now, automation_id)
            c.execute(
                "UPDATE schedules SET next_run=:due,last_job_id=:job WHERE id=:id",
                {"id": automation_id, "due": now + interval, "job": job["id"]},
            )
        return job

    def run_now(self, request_id, automation_id="discovery"):
        recipe_for(automation_id)
        key = (
            f"manual_scan:{self.settings.repo}:{request_id}"
            if automation_id == "discovery"
            else f"manual_automation:{automation_id}:{self.settings.repo}:{request_id}"
        )
        if prior := self.store.by_key(key):
            return prior
        if blocker := configuration_blocker(automation_id, self.settings):
            raise ScheduleConflict(blocker)
        self._reconcile_maintenance(automation_id)
        sha = self._revision()
        with self.store.connect() as c:
            c.lock()
            # Recheck after the network read to serialize double clicks and retries.
            prior = c.execute("SELECT * FROM jobs WHERE dedup=:key", {"key": key}).fetchone()
            if prior:
                return self.store.decode(prior)
            active = self._active(c, automation_id)
            if active:
                raise ScheduleConflict(
                    "This automation already has a run active or awaiting attention"
                )
            return self._insert(c, key, sha, "manual", time.time(), automation_id)

    def overview(self):
        row = self.schedule()
        jobs = attributed_jobs(self.store.operational_jobs())
        holds = [j for j in jobs if j["state"] in {"needs_attention", "unknown_effect"}]
        active = [j for j in jobs if j["state"] in {"running", "dispatching"}]
        with self.store.connect() as c:
            delivered = c.execute(
                "SELECT COUNT(*) AS count,MAX(received) AS last_received FROM deliveries"
            ).fetchone()
        return {
            "repository": self.settings.repo,
            "branch": self.settings.branch,
            "enabled": self.settings.enabled,
            "schedule": row,
            "catalogue": [
                {
                    **self.schedule(identity),
                    "description": recipe.description,
                    "category": recipe.category,
                    "kind": recipe.kind,
                    "configuration_required": configuration_blocker(identity, self.settings),
                    "error": self.store.recall("schedule_error:" + identity),
                    "run_count": sum(
                        any(a["id"] == identity for a in j["automations"]) for j in jobs
                    ),
                }
                for identity, recipe in RECIPES.items()
            ],
            "automation_history": [j for j in jobs if j["automations"]][:100],
            "worker": self.store.recall("worker_status", {}),
            "holds": holds,
            "active": active,
            "sessions_used": self.store.session_count(excluding=""),
            "session_limit": self.settings.max_sessions,
            "max_acu": self.settings.max_acu,
            "history": [j for j in jobs if j["kind"] == "scan"][:20],
            "triggers": [
                {
                    "name": "Labelled issues",
                    "event": f"issues · {self.settings.label}",
                    "enabled": True,
                    "last_poll": self.store.recall("last_issue_poll", {}).get("at"),
                },
                {
                    "name": "Dependabot updates",
                    "event": "pull_request · Dependabot in the fork",
                    "enabled": self.settings.dependabot_enabled,
                    "last_poll": self.store.recall("dependabot_poll", {}).get("at"),
                },
                {
                    "name": "PR release validation",
                    "event": "pull_request · tracked PR or cognition:validate",
                    "enabled": True,
                    "last_poll": self.store.recall("pr_validation_poll", {}).get("at"),
                },
            ],
            "webhook": {"configured": bool(self.settings.webhook_secret), **dict(delivered)},
        }
