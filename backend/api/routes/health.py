"""Liveness and database-aware health endpoints."""

import asyncio
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.constants import APP_VERSION
from backend.db.session import get_async_session

router = APIRouter(tags=["service"])
DatabaseSession = Annotated[AsyncSession, Depends(get_async_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


class DatabaseHealth(BaseModel):
    healthy: bool
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    project: str
    version: str
    services: dict[str, DatabaseHealth]


@router.get("/healthz", summary="Check whether the API process is alive")
async def liveness(settings: SettingsDependency) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.project_name,
        "version": APP_VERSION,
        "llm_provider": settings.llm_provider.value,
    }


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, db: DatabaseSession, settings: SettingsDependency
) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        database = DatabaseHealth(healthy=True)
        health_status = "healthy"
    except Exception as error:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        database = DatabaseHealth(healthy=False, error=type(error).__name__)
        health_status = "unhealthy"
    services = {"database": database}
    if os.getenv("WEATHER_CHECK_SERVICES") == "true":

        async def probe(name: str, url: str) -> tuple[str, DatabaseHealth]:
            try:
                if name == "redis":
                    async with Redis.from_url(
                        url, socket_timeout=2, socket_connect_timeout=2
                    ) as client:
                        await client.ping()
                else:
                    async with httpx.AsyncClient(timeout=2) as client:
                        (await client.get(url)).raise_for_status()
                return name, DatabaseHealth(healthy=True)
            except Exception as exc:
                return name, DatabaseHealth(healthy=False, error=type(exc).__name__)

        services.update(
            await asyncio.gather(
                probe("redis", settings.redis_url),
                probe(
                    "qdrant",
                    os.getenv("WEATHER_QDRANT_URL", "http://localhost:6333")
                    + "/readyz",
                ),
            )
        )
        if any(not service.healthy for service in services.values()):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            health_status = "unhealthy"
    return HealthResponse(
        status=health_status,
        project=settings.project_name,
        version=APP_VERSION,
        services=services,
    )
