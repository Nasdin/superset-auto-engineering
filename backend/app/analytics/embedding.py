"""Server-issued, dashboard-scoped guest tokens. Browser input never selects resources or SQL."""

import hashlib
import json
import os
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from .metrics import months_before

router = APIRouter(prefix="/api/analytics/superset", tags=["superset analytics"])


class Selection(BaseModel):
    repository: str = "apache/superset"
    end: date = Field(default_factory=lambda: datetime.now(UTC).date() - timedelta(days=1))
    days: int = Field(default=30, ge=7, le=180)
    comparison: Literal["six_months", "previous", "custom"] = "six_months"
    baseline_end: date | None = None
    author: str = Field(default="", max_length=100)
    label: str = Field(default="", max_length=200)
    base: str = Field(default="", max_length=200)
    kind: Literal["", "fix", "dependency", "feature", "revert", "other", "bot"] = ""
    cadence: Literal["monthly", "rolling"] = "monthly"
    layout: Literal["desktop", "mobile"] = "desktop"
    provenance: Literal["all", "tracked", "untracked"] = "all"

    def resolved(self, fork):
        if self.repository not in {"apache/superset", fork}:
            raise ValueError("Repository is outside analytics scope")
        if not date(2010, 1, 1) <= self.end < datetime.now(UTC).date():
            raise ValueError("Choose a completed UTC day from 2010 onward")
        baseline = (
            self.baseline_end
            if self.comparison == "custom"
            else self.end - timedelta(days=self.days)
            if self.comparison == "previous"
            else months_before(self.end)
        )
        if baseline is None or not date(2009, 1, 1) <= baseline < self.end:
            raise ValueError("Baseline end must precede the current end date")
        return {
            "repository": self.repository,
            "window_end": self.end.isoformat(),
            "baseline_end": baseline.isoformat(),
            "days": self.days,
            **self.model_dump(include={"author", "label", "base", "kind", "provenance"}),
        }


def remember_selection(store, values):
    # Superset includes guest RLS in its native chart cache key. A revision salt
    # changes the server-owned selection_id after ingestion, without accepting
    # SQL/cache keys from the browser or sharing a cohort across repositories.
    identity = hashlib.sha256(
        json.dumps(
            {**values, "data_revision": store.revision(values["repository"])}, sort_keys=True
        ).encode()
    ).hexdigest()
    with store.connect() as db:
        db.execute(
            "DELETE FROM analytics_selections WHERE requested_at<:cutoff",
            {"cutoff": time.time() - 7 * 86400},
        )
        db.execute(
            """INSERT INTO analytics_selections(selection_id,repository,window_end,baseline_end,author,label,base,kind,provenance,days,requested_at)
        VALUES(:selection_id,:repository,:window_end,:baseline_end,:author,:label,:base,:kind,:provenance,:days,:requested_at)
        ON CONFLICT(selection_id) DO UPDATE SET requested_at=excluded.requested_at""",
            {**values, "selection_id": identity, "requested_at": time.time()},
        )
    return identity


class SupersetClient:
    def __init__(self, internal_url, password, client=None):
        self.client = client or httpx.Client(
            base_url=internal_url.rstrip("/"),
            timeout=httpx.Timeout(30, connect=5, pool=5, write=5),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
        )
        self.password = password
        self.access_token = ""
        self.expires = 0
        self.lock = threading.Lock()

    def _login(self):
        response = self.client.post(
            "/api/v1/security/login",
            json={
                "username": "cognition-issuer",
                "password": self.password,
                "provider": "db",
                "refresh": False,
            },
        )
        response.raise_for_status()
        self.access_token = response.json()["access_token"]
        self.expires = time.monotonic() + 240

    def guest_token(self, dashboard_id, selection_id):
        # The only SQL interpolated into guest RLS is a server-generated digest.
        if len(selection_id) != 64 or any(c not in "0123456789abcdef" for c in selection_id):
            raise ValueError("Invalid server selection identity")
        if not self.lock.acquire(timeout=5):
            raise httpx.PoolTimeout("Superset token issuer is busy")
        try:
            if time.monotonic() >= self.expires:
                self._login()
            payload = {
                "user": {
                    "username": "cognition-viewer",
                    "first_name": "Cognition",
                    "last_name": "Viewer",
                },
                "resources": [{"type": "dashboard", "id": dashboard_id}],
                "rls": [{"clause": f"selection_id = '{selection_id}'"}],
            }
            for attempt in range(2):
                response = self.client.post(
                    "/api/v1/security/guest_token/",
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    json=payload,
                )
                # A service restart/token rotation may invalidate the cached issuer
                # JWT early. Reauthenticate once; never loop on denied permissions.
                if response.status_code == 401 and attempt == 0:
                    self.expires = 0
                    self._login()
                    continue
                response.raise_for_status()
                return response.json()["token"]
        finally:
            self.lock.release()

    def close(self):
        self.client.close()


@router.post("/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    engine = request.app.state.engine
    client = getattr(request.app.state, "superset", None)
    configured = engine.store.recall("superset_dashboard")
    if client is None or not configured or not engine.settings.database.startswith("postgresql"):
        raise HTTPException(
            503,
            "Superset analytics is not configured. No replacement charts or demo values are shown.",
        )
    try:
        selection = Selection.model_validate(dict(request.query_params))
        values = selection.resolved(engine.settings.repo)
    except (ValidationError, ValueError) as error:
        raise HTTPException(422, "Invalid analytics filters") from error
    dashboard_key = {
        ("monthly", "desktop"): "dashboard_id",
        ("rolling", "desktop"): "rolling_dashboard_id",
        ("monthly", "mobile"): "mobile_dashboard_id",
        ("rolling", "mobile"): "mobile_rolling_dashboard_id",
    }[selection.cadence, selection.layout]
    dashboard_id = configured.get(dashboard_key)
    if not dashboard_id:
        raise HTTPException(503, "This analytics layout has not been provisioned")
    identity = remember_selection(request.app.state.analytics, values)
    try:
        token = client.guest_token(dashboard_id, identity)
    except (httpx.HTTPError, KeyError, ValueError) as error:
        raise HTTPException(
            502, "Superset could not open this dashboard. Check the BI service connection."
        ) from error
    return {
        "dashboard_id": dashboard_id,
        "superset_url": os.environ["SUPERSET_PUBLIC_URL"],
        "token": token,
        "selection_id": identity,
    }
