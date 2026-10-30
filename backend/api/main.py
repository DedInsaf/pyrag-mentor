from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import auth, health
from backend.core.config import Settings, get_settings
from backend.core.constants import APP_VERSION
from backend.db.models import Base
from backend.db.session import async_engine
from backend.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independently testable FastAPI application instance."""

    resolved_settings = settings or get_settings()
    setup_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting %s version %s in %s mode",
            resolved_settings.project_name,
            APP_VERSION,
            "debug" if resolved_settings.debug else "production",
        )
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("Database schema is ready")
        yield
        await async_engine.dispose()
        logger.info("Stopping %s", resolved_settings.project_name)

    application = FastAPI(
        title=resolved_settings.project_name,
        version=APP_VERSION,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router)
    application.include_router(auth.router)

    return application


app = create_app()
