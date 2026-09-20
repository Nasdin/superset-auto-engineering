"""Application factory: HTTP wiring and resource lifetime, no workflow logic."""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .automation.config import Settings
from .automation.providers import Providers
from .automation.routes import router as live_router
from .automation.runtime import create_runtime
from .demo import create_demo_router


def create_app(
    settings: Settings | None = None,
    *,
    demo_database: Path | None = None,
    static_directory: Path = Path("static"),
    provider_factory: Callable[[Settings], Providers] = Providers,
) -> FastAPI:
    configured = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        with create_runtime(configured, provider_factory=provider_factory) as engine:
            application.state.engine = engine
            yield

    application = FastAPI(title="Cognition Evidence API", version="0.1.0", lifespan=lifespan)
    application.include_router(
        create_demo_router(demo_database or Path(os.getenv("DATABASE_PATH", "data/cognition.db")))
    )
    application.include_router(live_router)
    if static_directory.is_dir():
        application.mount("/", StaticFiles(directory=static_directory, html=True), name="frontend")
    return application


app = create_app()
