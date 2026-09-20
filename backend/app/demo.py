"""Isolated fixture API with its own local event database."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .demo_fixtures import CHECKS, SHA, WORKFLOWS


class Decision(BaseModel):
    sha: str
    decision: str = Field(pattern="^(approved|changes_requested)$")
    note: str = Field(min_length=3, max_length=2000)


class Event(BaseModel):
    delivery_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=3, max_length=200)


def create_demo_router(database: Path) -> APIRouter:
    router = APIRouter()

    @contextmanager
    def connect():
        database.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(database)
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, delivery TEXT UNIQUE, kind TEXT, payload TEXT, created TEXT)"
        )
        con.commit()
        try:
            with con:
                yield con
        finally:
            con.close()

    @router.get("/api/health")
    def health():
        with connect() as con:
            con.execute("SELECT 1")
        return {"status": "ok", "mode": "demo"}

    @router.get("/api/dashboard")
    def dashboard():
        with connect() as con:
            events = [
                dict(r) for r in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50")
            ]
        for event in events:
            event["payload"] = json.loads(event["payload"])
        latest = next(
            (
                e["payload"]["decision"]
                for e in events
                if e["kind"] == "demo_decision" and e["payload"]["sha"] == SHA
            ),
            None,
        )
        return dict(
            mode="demo",
            repository="apache/superset",
            candidate=dict(
                id="RC-014",
                sha=SHA,
                branch="integration/rc-014",
                validator="DV-086",
                status="demo_" + latest if latest else "needs_review",
            ),
            checks=CHECKS,
            workflows=WORKFLOWS,
            events=events,
        )

    @router.post("/api/demo/decisions")
    def decide(body: Decision):
        if body.sha != SHA:
            raise HTTPException(409, "Candidate changed. Refresh and review the current SHA.")
        now = datetime.now(UTC).isoformat()
        with connect() as con:
            con.execute(
                "INSERT INTO events (kind,payload,created) VALUES (?,?,?)",
                ("demo_decision", body.model_dump_json(), now),
            )
        return {"status": "recorded", "mode": "demo", "merged": False}

    @router.post("/api/demo/events")
    def event(body: Event):
        now = datetime.now(UTC).isoformat()
        with connect() as con:
            cursor = con.execute(
                "INSERT OR IGNORE INTO events (delivery,kind,payload,created) VALUES (?,?,?,?)",
                (body.delivery_id, "issue_received", body.model_dump_json(), now),
            )
            created = cursor.rowcount == 1
        return {
            "status": "queued" if created else "duplicate",
            "mode": "demo",
            "devin_started": False,
        }

    @router.post("/api/releases/approve")
    def approve():
        raise HTTPException(
            409, "Demo evidence cannot approve a real release. Live validation is not connected."
        )

    return router
