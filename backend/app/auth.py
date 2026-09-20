"""Shared reviewer login, separate from privileged operator authentication."""

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Column, Float, Integer, MetaData, String, Table
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse

COOKIE = "cognition_session"
SESSION_SECONDS = 8 * 60 * 60
# Each scrypt check uses about 16 MiB; cap parallel work on the small API host.
PASSWORD_CHECKS = BoundedSemaphore(2)
metadata = MetaData()
Table(
    "reviewer_sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("password_version", String(64), nullable=False),
    Column("expires", Float, nullable=False),
)
Table(
    "reviewer_login_limits",
    metadata,
    Column("bucket", String(32), primary_key=True),
    Column("started", Float, nullable=False),
    Column("attempts", Integer, nullable=False),
)


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    password_hash: str = ""
    secure_cookie: bool = True

    @classmethod
    def from_env(cls):
        settings = cls(
            enabled=os.getenv("AUTH_ENABLED", "false").lower() == "true",
            password_hash=os.getenv("REVIEWER_PASSWORD_HASH", ""),
            secure_cookie=os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true",
        )
        if settings.enabled:
            try:
                scheme, salt, digest = settings.password_hash.split(":")
                if (
                    scheme != "scrypt"
                    or len(bytes.fromhex(salt)) != 16
                    or len(bytes.fromhex(digest)) != 64
                ):
                    raise ValueError("Invalid password hash")
            except ValueError as error:
                raise ValueError(
                    "Login requires a valid REVIEWER_PASSWORD_HASH; run configure_login.py"
                ) from error
        return settings


class ReviewerAuth:
    def __init__(self, database, settings: AuthSettings):
        self.database = database
        self.settings = settings
        self.version = hashlib.sha256(settings.password_hash.encode()).hexdigest()
        if settings.enabled:
            database.initialize(metadata)

    def authenticated(self, token: str | None) -> bool:
        if not self.settings.enabled:
            return True
        if not token or len(token) > 128:
            return False
        with self.database.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM reviewer_sessions WHERE token_hash=:token AND expires>:now AND password_version=:version",
                    {
                        "token": hashlib.sha256(token.encode()).hexdigest(),
                        "now": time.time(),
                        "version": self.version,
                    },
                ).fetchone()
                is not None
            )

    def login(self, password: str) -> str:
        now = time.time()
        # Global, durable ceiling bounds password hashing work, even with spoofed
        # proxy addresses or multiple processes. It resets after at most 60s.
        with self.database.connect() as connection:
            connection.lock()
            row = connection.execute(
                "SELECT * FROM reviewer_login_limits WHERE bucket='global'"
            ).fetchone()
            if row and row["started"] > now - 60 and row["attempts"] >= 20:
                raise HTTPException(
                    429,
                    "Too many attempts. Try again in one minute.",
                    headers={"Retry-After": "60"},
                )
            started = row["started"] if row and row["started"] > now - 60 else now
            attempts = row["attempts"] + 1 if row and started == row["started"] else 1
            connection.execute(
                "INSERT INTO reviewer_login_limits(bucket,started,attempts) VALUES('global',:started,:attempts) ON CONFLICT(bucket) DO UPDATE SET started=:started,attempts=:attempts",
                {"started": started, "attempts": attempts},
            )
        _, salt, expected = self.settings.password_hash.split(":")
        with PASSWORD_CHECKS:
            actual = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
            ).hex()
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(401, "Incorrect password.")
        token = secrets.token_urlsafe(32)
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM reviewer_sessions WHERE expires<=:now OR password_version!=:version",
                {"now": now, "version": self.version},
            )
            connection.execute(
                "INSERT INTO reviewer_sessions(token_hash,password_version,expires) VALUES(:token,:version,:expires)",
                {
                    "token": hashlib.sha256(token.encode()).hexdigest(),
                    "version": self.version,
                    "expires": now + SESSION_SECONDS,
                },
            )
        return token

    def logout(self, token: str | None):
        if token:
            with self.database.connect() as connection:
                connection.execute(
                    "DELETE FROM reviewer_sessions WHERE token_hash=:token",
                    {"token": hashlib.sha256(token.encode()).hexdigest()},
                )


def require_intent(request: Request):
    # Cross-origin forms cannot set this header; CORS is deliberately disabled.
    if (
        request.headers.get("x-cognition-intent") != "session"
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(403, "Same-origin session request required")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.get("/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    auth = request.app.state.reviewer_auth
    return {
        "enabled": auth.settings.enabled,
        "authenticated": auth.authenticated(request.cookies.get(COOKIE)),
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    require_intent(request)
    auth = request.app.state.reviewer_auth
    if not auth.settings.enabled:
        raise HTTPException(409, "Login is not enabled")
    token = auth.login(body.password)
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=auth.settings.secure_cookie,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    require_intent(request)
    auth = request.app.state.reviewer_auth
    if auth.settings.enabled:
        auth.logout(request.cookies.get(COOKIE))
    response.delete_cookie(
        COOKIE, path="/", secure=auth.settings.secure_cookie, httponly=True, samesite="strict"
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}


@router.get("/verify")
def verify(request: Request):
    # Used by Caddy for Superset; it must fail closed even if local auth is disabled.
    auth = request.app.state.reviewer_auth
    if auth.settings.enabled and auth.authenticated(request.cookies.get(COOKIE)):
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/?login=1", status_code=303, headers={"Cache-Control": "no-store"})
    return JSONResponse(
        {"detail": "Sign in required"}, status_code=401, headers={"Cache-Control": "no-store"}
    )


def install_auth(application, settings: AuthSettings, operator_token: str):
    application.include_router(router)

    @application.middleware("http")
    async def protect_api(request: Request, call_next):
        path = request.url.path
        public = path in {
            "/api/health",
            "/api/auth/session",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/verify",
        }
        webhook = path == "/api/live/webhooks/github" and request.method == "POST"
        operator = bool(operator_token) and hmac.compare_digest(
            request.headers.get("authorization", "").encode(), ("Bearer " + operator_token).encode()
        )
        protected = path.startswith("/api/") or path in {"/docs", "/redoc", "/openapi.json"}
        if settings.enabled and protected and not (public or webhook or operator):
            auth = request.app.state.reviewer_auth
            if not await run_in_threadpool(auth.authenticated, request.cookies.get(COOKIE)):
                return JSONResponse(
                    {"detail": "Sign in required"},
                    status_code=401,
                    headers={"Cache-Control": "no-store"},
                )
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                try:
                    require_intent(request)
                except HTTPException as error:
                    return JSONResponse(
                        {"detail": error.detail},
                        status_code=error.status_code,
                        headers={"Cache-Control": "no-store"},
                    )
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
        return response
