"""Operator recovery changes durable intent only; the worker owns provider execution."""

import json
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .engine import Engine
from .resilience import Recovery
from .routes import get_engine, operator

router = APIRouter(prefix="/api/live", tags=["recovery"])


class Intent(BaseModel):
    request_id: UUID


class PublicationIntent(Intent):
    key: str


@router.get("/resilience")
def resilience(eng: Engine = Depends(get_engine)):
    return Recovery(eng.store).overview()


def replay(eng, kind, identity, request_id):
    key = f"replay:{kind}:{identity}:{request_id}"
    now = time.time()
    with eng.store.connect() as c:
        c.lock()
        prior = c.execute("SELECT value FROM memory WHERE key=:key", {"key": key}).fetchone()
        if prior:
            return json.loads(prior["value"])
        if kind == "job":
            row = c.execute("SELECT * FROM jobs WHERE id=:id", {"id": identity}).fetchone()
            if not row:
                raise HTTPException(404, "Job not found")
            if row["state"] not in {"blocked", "dead_letter"}:
                raise HTTPException(
                    409,
                    "Only a blocked or dead-letter job may be retried. Uncertain effects require provider reconciliation.",
                )
            state = "running" if row["session_id"] else "queued"
            c.execute(
                "UPDATE jobs SET state=:state,error=NULL,next_poll=0,lease_until=0,updated=:now WHERE id=:id",
                {"state": state, "now": now, "id": identity},
            )
            result = {"status": "requeued", "job_id": identity}
            c.execute("DELETE FROM recovery WHERE key=:key", {"key": "job:" + identity})
        elif kind == "publication":
            row = c.execute(
                "SELECT * FROM publications WHERE key=:key", {"key": identity}
            ).fetchone()
            if not row:
                raise HTTPException(404, "Publication not found")
            if row["state"] not in {"failed", "dead_letter", "blocked", "delivered"}:
                raise HTTPException(
                    409,
                    "Uncertain or active publication cannot be replayed. Reconcile the provider receipt first.",
                )
            c.execute(
                "UPDATE publications SET state=:state,error=NULL,updated=:now WHERE key=:key",
                {
                    "state": "delivered" if row["receipt"] else "pending",
                    "now": now,
                    "key": identity,
                },
            )
            result = {"status": "requeued", "key": identity}
            c.execute("DELETE FROM recovery WHERE key=:key", {"key": "publication:" + identity})
        elif kind == "inbox":
            row = c.execute("SELECT * FROM github_inbox WHERE id=:id", {"id": identity}).fetchone()
            if not row:
                raise HTTPException(404, "Delivery not found")
            if row["state"] not in {"blocked", "dead_letter"}:
                raise HTTPException(409, "Only blocked or dead-letter intake can be retried")
            c.execute(
                "UPDATE github_inbox SET state='pending',error=NULL,next_retry=0,updated=:now WHERE id=:id",
                {"id": identity, "now": now},
            )
            c.execute("DELETE FROM recovery WHERE key=:key", {"key": "inbox:" + identity})
            result = {"status": "requeued", "delivery_id": identity}
        else:
            if identity not in {"devin", "github", "slack"}:
                raise HTTPException(404, "Provider not found")
            c.execute("DELETE FROM memory WHERE key=:key", {"key": "breaker:" + identity})
            result = {"status": "probe_enabled", "provider": identity}
        c.execute(
            "INSERT INTO memory VALUES(:key,:value,:now)",
            {"key": key, "value": json.dumps(result), "now": now},
        )
        c.execute(
            "INSERT INTO audit(job_id,kind,detail,created) VALUES(:job,'operator_recovery',:detail,:now)",
            {
                "job": identity if kind == "job" else None,
                "detail": json.dumps(
                    {"kind": kind, "identity": identity, "request_id": str(request_id)}
                ),
                "now": now,
            },
        )
        return result


@router.post("/recovery/jobs/{job_id}", dependencies=[Depends(operator)])
def retry_job(job_id: str, body: Intent, eng: Engine = Depends(get_engine)):
    return replay(eng, "job", job_id, body.request_id)


@router.post("/recovery/publications", dependencies=[Depends(operator)])
def retry_publication(body: PublicationIntent, eng: Engine = Depends(get_engine)):
    return replay(eng, "publication", body.key, body.request_id)


@router.post("/recovery/providers/{provider}", dependencies=[Depends(operator)])
def probe_provider(provider: str, body: Intent, eng: Engine = Depends(get_engine)):
    return replay(eng, "provider", provider, body.request_id)


@router.post("/recovery/inbox/{delivery_id}", dependencies=[Depends(operator)])
def retry_intake(delivery_id: str, body: Intent, eng: Engine = Depends(get_engine)):
    return replay(eng, "inbox", delivery_id, body.request_id)
