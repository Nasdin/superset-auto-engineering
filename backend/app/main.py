"""Application factory: HTTP wiring and resource lifetime, no workflow logic."""

import os
from collections.abc import Callable
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import contextmanager_in_threadpool
from fastapi.staticfiles import StaticFiles

from .analytics.embedding import SupersetClient
from .analytics.embedding import router as superset_router
from .analytics.routes import router as analytics_router
from .analytics.store import AnalyticsStore
from .auth import AuthSettings, ReviewerAuth, install_auth
from .automation.artifacts import public_evidence
from .automation.config import Settings
from .automation.controls import router as controls_router
from .automation.providers import Providers
from .automation.recovery_routes import router as recovery_router
from .automation.routes import router as live_router
from .automation.runtime import create_runtime
from .demo import create_demo_router
from .http_errors import InfrastructureErrorsMiddleware


def create_app(
    settings: Settings | None = None,
    *,
    demo_database: Path | None = None,
    analytics_seed: Path | None = None,
    static_directory: Path = Path("static"),
    auth_settings: AuthSettings | None = None,
    provider_factory: Callable[[Settings], Providers] = Providers,
) -> FastAPI:
    configured = settings if settings is not None else Settings.from_env()

    authentication = auth_settings or AuthSettings.from_env()

    @contextmanager
    def resources(application: FastAPI):
        with ExitStack() as stack:
            engine = stack.enter_context(
                create_runtime(configured, provider_factory=provider_factory)
            )
            application.state.engine = engine
            application.state.reviewer_auth = ReviewerAuth(engine.store.database, authentication)
            application.state.analytics = AnalyticsStore(
                configured.analytics_database, seed=analytics_seed
            )
            stack.callback(application.state.analytics.database.close)
            application.state.superset = (
                SupersetClient(
                    os.environ["SUPERSET_INTERNAL_URL"],
                    os.environ["ANALYTICS_SUPERSET_SERVICE_PASSWORD"],
                )
                if os.getenv("SUPERSET_INTERNAL_URL")
                and os.getenv("ANALYTICS_SUPERSET_SERVICE_PASSWORD")
                else None
            )
            if application.state.superset:
                stack.callback(application.state.superset.close)
            yield

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        async with contextmanager_in_threadpool(resources(application)):
            yield

    application = FastAPI(title="Cognition Evidence API", version="0.1.0", lifespan=lifespan)

    install_auth(application, authentication, configured.operator_token)
    # Outside auth: its database lookups can fail before a route is reached.
    application.add_middleware(InfrastructureErrorsMiddleware)

    @application.get("/api/health/live")
    async def liveness():
        return {"status": "alive"}

    @application.get("/api/health")
    def health(request: Request):
        with request.app.state.engine.store.connect() as connection:
            connection.execute("SELECT 1 FROM jobs LIMIT 1")
        return {"status": "ok", "mode": "live", "automation_enabled": configured.enabled}

    if not configured.database.startswith("postgresql") or os.getenv("ENABLE_DEMO") == "true":
        application.include_router(
            create_demo_router(
                demo_database or Path(os.getenv("DATABASE_PATH", "data/cognition.db"))
            )
        )
    application.include_router(live_router)
    application.include_router(controls_router)
    application.include_router(recovery_router)
    application.include_router(analytics_router)
    application.include_router(superset_router)

    @application.get("/public-evidence/{name}", include_in_schema=False)
    def published_evidence(name: str):
        return public_evidence(configured.artifacts, name)

    if static_directory.is_dir():
        application.mount("/", StaticFiles(directory=static_directory, html=True), name="frontend")
    return application


app = create_app(analytics_seed=Path(__file__).parent / "seeds" / "github-history.sqlite3")
