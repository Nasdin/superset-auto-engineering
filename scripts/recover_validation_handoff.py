"""Reassess a completed legacy session using its own v2 report; never start paid work."""

import argparse

from app.automation.config import Settings
from app.automation.runtime import create_runtime


def recover(engine, job_id):
    job = engine.store.get(job_id)
    if (
        not job
        or job["kind"] != "validation"
        or job["state"] not in {"validation_failed", "needs_attention", "review_ready"}
    ):
        raise ValueError("Expected a finished/paused validation job")
    session = engine.providers.session(job["session_id"])
    if session.get("session_id") != job[
        "session_id"
    ] or f"cognition-job:{job_id}" not in session.get("tags", []):
        raise ValueError("Provider session identity does not match")
    result = session.get("structured_output")
    if not isinstance(result, dict) or result.get("task_complete") is not True:
        raise ValueError("Session has no completed handoff")
    if session.get("status_detail") not in {"finished", "waiting_for_user"}:
        raise ValueError("Session is still working")
    engine.finish_validation(job, result)
    engine.store.audit(job_id, "provider_handoff_reassessed", {"session_id": job["session_id"]})
    observed = engine.store.get(job_id)
    print({"job_id": job_id, "state": observed["state"], "error": observed["error"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    with create_runtime(Settings.from_env()) as engine:
        recover(engine, parser.parse_args().job)
