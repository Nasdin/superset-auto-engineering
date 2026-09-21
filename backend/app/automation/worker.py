"""One durable worker process; start with python -m app.automation.worker."""

import fcntl
import logging
import time
from contextlib import contextmanager

from .config import Settings
from .dependencies import DependencyService
from .inbox import Inbox
from .learning import LearningService
from .patches import PatchService
from .pr_validation import PullRequestValidationService
from .resilience import Recovery, backoff
from .runtime import create_runtime


def cycle(engine):
    s, db = engine.settings, engine.store
    # Stopping new paid dispatch must not stop observation, delivery or freshness.
    tasks = [("outbox", engine.flush_publication)]
    if s.enabled and s.github_token and s.devin_key and s.autonomous_remediation:
        from .handoffs import HandoffRecovery
        from .outbox import PublicationOutbox

        tasks.append(("handoff_recovery", HandoffRecovery(engine).tick))
        tasks.append(
            ("readiness_receipts", PublicationOutbox(s, db, engine.providers).reconcile_readiness)
        )
    if s.github_token and s.devin_key and time.time() - db.recall("last_remediation_tick", 0) >= 60:
        from .remediation import RemediationService

        tasks.append(("remediation", RemediationService(s, db, engine.providers).reconcile))
    if s.github_token:
        tasks.append(("inbox", Inbox(engine).tick))
    if s.github_token and s.devin_key:
        tasks.append(("jobs", engine.tick))
    if s.enabled and s.github_token:
        tasks.append(("batch", engine.schedule_batch))
    if s.devin_key and time.time() - db.recall("learning_sync", {}).get("at", 0) >= 300:
        tasks.append(("learning", LearningService(s, db, engine.providers).sync))
    if s.github_token and time.time() - db.recall("last_issue_poll", {}).get("at", 0) >= 60:
        tasks += [
            ("github_events", engine.poll_issues),
            ("dependabot", DependencyService(s, db, engine.providers).poll),
            ("patches", PatchService(s, db, engine.providers).poll),
            ("pr_validation", PullRequestValidationService(s, db, engine.providers).poll),
            ("freshness", engine.refresh_readiness),
        ]
    if s.enabled and s.github_token and time.time() - db.recall("last_schedule_tick", 0) >= 60:
        tasks += [("schedule", engine.schedule_automations)]
    failures = []
    for name, action in tasks:
        try:
            action()
            if name == "remediation":
                db.remember("last_remediation_tick", time.time())
            if name == "schedule":
                db.remember("last_schedule_tick", time.time())
        except Exception as e:
            # Isolate intake outages from polling already-paid sessions.
            failures.append({"stage": name, "error": type(e).__name__})
            logging.warning("Worker %s: %s", name, type(e).__name__)
    recovery = Recovery(db).overview()
    degraded = (
        failures
        or any(x.get("state") == "open" for x in recovery["breakers"])
        or any(recovery["counts"][k] for k in ("retrying", "dead_letters", "held", "uncertain"))
    )
    db.remember(
        "worker_status",
        {
            "state": "degraded" if degraded else "running" if s.enabled else "observing",
            "at": time.time(),
            "failures": failures,
            "recovery": recovery["counts"],
        },
    )


@contextmanager
def singleton(directory):
    """OS lock in the shared durable volume: only one local worker, no expiring lease.

    Intentionally single-host. A distributed worker requires fencing tokens and
    isolated executors, not scaling this Compose service across unrelated disks.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    with singleton(settings.artifacts.parent):
        failures = 0
        while True:
            try:
                with create_runtime(settings) as engine:
                    while True:
                        cycle(engine)
                        failures = 0
                        time.sleep(settings.poll_seconds)
            except Exception as error:
                # Database outage, disk-full or pool failure: retain durable state,
                # release broken connections and retry startup without tight looping.
                failures += 1
                logging.error("Worker infrastructure unavailable: %s", type(error).__name__)
                time.sleep(min(60, backoff(failures)))


if __name__ == "__main__":
    main()
