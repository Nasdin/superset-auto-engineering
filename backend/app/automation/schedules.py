"""Durable, bounded discovery scheduling; manual intent is distinct from recurrence."""

import json
import time
import uuid


class ScheduleConflict(ValueError):
    pass


class ScheduleService:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    def schedule(self):
        now = time.time()
        interval = self.settings.scan_interval or 86400
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO schedules(id,name,enabled,interval_seconds,next_run,updated) "
                "VALUES('discovery','Autonomous correctness scan',:enabled,:interval,:due,:now) "
                "ON CONFLICT DO NOTHING",
                {
                    "enabled": int(self.settings.scan_interval > 0),
                    "interval": interval,
                    "due": int(now // interval) * interval,
                    "now": now,
                },
            )
            return dict(c.execute("SELECT * FROM schedules WHERE id='discovery'").fetchone())

    def configure(self, enabled, interval, expected_updated):
        self.schedule()
        if interval not in {3600, 21600, 86400, 604800}:
            raise ValueError("Choose hourly, six-hourly, daily or weekly")
        now = time.time()
        with self.store.connect() as c:
            c.lock()
            row = c.execute("SELECT * FROM schedules WHERE id='discovery'").fetchone()
            if row["updated"] != expected_updated:
                raise ScheduleConflict("Schedule changed; refresh before saving")
            # Editing a recurrence never creates an immediate surprise paid run.
            due = now + interval if enabled else row["next_run"]
            c.execute(
                "UPDATE schedules SET enabled=:enabled,interval_seconds=:interval,"
                "next_run=:due,updated=:now WHERE id='discovery'",
                {"enabled": int(enabled), "interval": interval, "due": due, "now": now},
            )
        self.store.audit(None, "schedule_configured", {"enabled": enabled, "interval": interval})
        return self.schedule()

    def _insert(self, c, key, sha, source, now):
        c.execute(
            "INSERT INTO jobs(id,dedup,kind,state,payload,created,updated) "
            "VALUES(:id,:key,'scan','queued',:payload,:now,:now) ON CONFLICT DO NOTHING",
            {
                "id": str(uuid.uuid4()),
                "key": key,
                "now": now,
                "payload": json.dumps(
                    {
                        "base_sha": sha,
                        "source": source,
                        "title": "Autonomous correctness scan",
                        "schedule_id": "discovery" if source == "schedule" else None,
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

    def tick(self):
        row = self.schedule()
        now = time.time()
        if not row["enabled"] or row["next_run"] > now:
            return self.store.get(row["last_job_id"]) if row["last_job_id"] else None
        sha = self._revision()
        with self.store.connect() as c:
            c.lock()
            current = c.execute("SELECT * FROM schedules WHERE id='discovery'").fetchone()
            if not current["enabled"] or current["next_run"] > now:
                return None
            # Coalesce missed ticks; never replay a backlog of paid scans after downtime.
            active = c.execute(
                "SELECT * FROM jobs WHERE kind='scan' AND state IN "
                "('queued','dispatching','running','needs_attention','unknown_effect') LIMIT 1"
            ).fetchone()
            if active:
                return self.store.decode(active)
            interval = current["interval_seconds"]
            bucket = int(now // interval)
            key = f"scan:{self.settings.repo}:{self.settings.branch}:{bucket}"
            job = self._insert(c, key, sha, "schedule", now)
            c.execute(
                "UPDATE schedules SET next_run=:due,last_job_id=:job WHERE id='discovery'",
                {"due": now + interval, "job": job["id"]},
            )
        return job

    def run_now(self, request_id):
        key = f"manual_scan:{self.settings.repo}:{request_id}"
        if prior := self.store.by_key(key):
            return prior
        sha = self._revision()
        with self.store.connect() as c:
            c.lock()
            # Recheck after the network read to serialize double clicks and retries.
            prior = c.execute("SELECT * FROM jobs WHERE dedup=:key", {"key": key}).fetchone()
            if prior:
                return self.store.decode(prior)
            active = c.execute(
                "SELECT id FROM jobs WHERE kind='scan' AND state IN "
                "('queued','dispatching','running','needs_attention','unknown_effect') LIMIT 1"
            ).fetchone()
            if active:
                raise ScheduleConflict("A discovery run is already active or awaiting attention")
            return self._insert(c, key, sha, "manual", time.time())

    def overview(self):
        row = self.schedule()
        jobs = self.store.operational_jobs()
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
