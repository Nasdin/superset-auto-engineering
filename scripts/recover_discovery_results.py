"""Recover missing legacy scan results from their original Devin session (read-only provider calls).

Run inside the configured application container. Does not create issues, sessions or PRs.
"""

import hashlib

from app.automation.config import Settings
from app.automation.runtime import create_runtime


def recover(engine):
    recovered = 0
    for job in engine.store.operational_jobs():
        if (
            job["kind"] != "scan"
            or job["state"] != "completed"
            or job["result"]
            or not job["session_id"]
        ):
            continue
        session = engine.providers.session(job["session_id"])
        result = session.get("structured_output")
        if session.get("session_id") != job["session_id"] or not isinstance(result, dict):
            continue
        findings = result.get("findings")
        if (
            not isinstance(findings, list)
            or len(findings) > 1
            or any(
                f.get("base_sha") != job["payload"]["base_sha"] or not f.get("reproduction")
                for f in findings
            )
        ):
            continue
        for finding in findings:
            fingerprint = hashlib.sha256(
                (engine.settings.repo + finding["title"]).encode()
            ).hexdigest()[:20]
            receipt = engine.store.recall("finding:" + fingerprint)
            if receipt:
                child = engine.store.by_key(f"issue:{engine.settings.repo}:{receipt['issue']}")
                if child and not child["parent_id"]:
                    engine.store.update(child["id"], parent_id=job["id"])
        engine.store.update(job["id"], result=result)
        engine.store.audit(
            job["id"],
            "legacy_result_recovered",
            {"session_id": job["session_id"], "source": "provider_readback"},
        )
        recovered += 1
    return recovered


if __name__ == "__main__":
    with create_runtime(Settings.from_env()) as engine:
        print({"recovered_discovery_results": recover(engine)})
