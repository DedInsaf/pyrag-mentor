"""FastAPI application factory and health endpoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.config import Settings, get_settings
from backend.core.constants import APP_VERSION, HEALTHCHECK_PATH
from backend.utils.logging import setup_logging

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Public liveness response without secrets or infrastructure details."""

    status: str
    service: str
    version: str
    llm_provider: str


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
        yield
        logger.info("Stopping %s", resolved_settings.project_name)

    application = FastAPI(
        title=resolved_settings.project_name,
        version=APP_VERSION,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get(
        HEALTHCHECK_PATH,
        response_model=HealthResponse,
        tags=["service"],
        summary="Check whether the API process is alive",
    )
    async def healthcheck() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=resolved_settings.project_name,
            version=APP_VERSION,
            llm_provider=resolved_settings.llm_provider.value,
        )

    return application


app = create_app()
