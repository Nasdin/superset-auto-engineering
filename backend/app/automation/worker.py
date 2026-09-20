"""One durable worker process; start with python -m app.automation.worker."""

import logging
import time

from .config import Settings
from .dependencies import DependencyService
from .runtime import create_runtime


def cycle(engine):
    s, db = engine.settings, engine.store
    if not (s.enabled and s.github_token and s.devin_key):
        db.remember("worker_status", {"state": "configuration_required", "at": time.time()})
        return
    tasks = [
        ("jobs", engine.tick),
        ("outbox", engine.flush_publication),
        ("batch", engine.schedule_batch),
    ]
    if time.time() - db.recall("last_issue_poll", {}).get("at", 0) >= 60:
        tasks += [
            ("github_events", engine.poll_issues),
            ("dependabot", DependencyService(s, db, engine.providers).poll),
            ("freshness", engine.refresh_readiness),
        ]
    if s.scan_interval > 0 and time.time() - db.recall("last_schedule_tick", 0) >= 60:
        tasks += [("schedule", engine.schedule_scan)]
    failures = []
    for name, action in tasks:
        try:
            action()
            if name == "schedule":
                db.remember("last_schedule_tick", time.time())
        except Exception as e:
            # Isolate intake outages from polling already-paid sessions.
            failures.append({"stage": name, "error": type(e).__name__})
            logging.warning("Worker %s: %s", name, type(e).__name__)
    db.remember(
        "worker_status",
        {
            "state": "degraded" if failures else "running",
            "at": time.time(),
            "failures": failures,
        },
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with create_runtime(Settings.from_env()) as engine:
        while True:
            cycle(engine)
            time.sleep(engine.settings.poll_seconds)


if __name__ == "__main__":
    main()
