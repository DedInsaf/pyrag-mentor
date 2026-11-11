# mypy: disable-error-code=untyped-decorator
import asyncio
import logging
import os
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from celery.signals import (  # type: ignore[import-untyped]
    worker_process_shutdown,
    worker_shutdown,
)
from sqlalchemy import delete, func, select

from backend.data.weather import Weather, forecast
from backend.db.models import KnowledgeBaseEntry, ResponseCache
from backend.db.session import AsyncSessionLocal, async_engine
from backend.retrieval.weather_index import reindex
from backend.services.weather import Engine, Mode, explain
from backend.worker.celery_app import app

log = logging.getLogger(__name__)
_loop: asyncio.AbstractEventLoop | None = None


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


@worker_process_shutdown.connect
@worker_shutdown.connect
def close_worker_loop(**kwargs: Any) -> None:
    global _loop
    if _loop is not None:
        _loop.run_until_complete(async_engine.dispose())
        _loop.close()
        _loop = None
        log.info("Worker event loop closed")


@app.task(name="weather.index")
def index_weather() -> int:
    async def task() -> int:
        async with AsyncSessionLocal() as session:
            return await reindex(session, os.environ["WEATHER_QDRANT_URL"])

    return run(task())


@app.task(name="weather.clear_cache")
def clear_cache() -> int:
    async def task() -> int:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                delete(ResponseCache)
                .where(
                    ResponseCache.category == "weather",
                    ResponseCache.created_at < datetime.now(UTC) - timedelta(hours=24),
                )
                .returning(ResponseCache.id)
            )
            count = len(rows.all())
            await session.commit()
            return count

    return run(task())


@app.task(name="weather.batch")
def batch_forecast(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def task() -> list[dict[str, Any]]:
        async def item(row: dict[str, Any]) -> dict[str, Any]:
            try:
                result = await forecast(row["latitude"], row["longitude"], row["hours"])
                return {
                    "forecast": result.model_dump(mode="json"),
                    "condition": result.condition,
                }
            except Exception as exc:
                return {"error": type(exc).__name__}

        results = []
        for start in range(0, len(items), 4):
            results.extend(
                await asyncio.gather(*(item(row) for row in items[start : start + 4]))
            )
        return results

    return run(task())


@app.task(name="weather.cache_stats")
def cache_stats() -> dict[str, int]:
    async def task() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(
                        func.count(), func.coalesce(func.sum(ResponseCache.hits), 0)
                    ).where(ResponseCache.category == "weather")
                )
            ).one()
            return {"entries": row[0], "hits": row[1]}

    return run(task())


@app.task(name="weather.memory_stats")
def memory_stats() -> int | None:
    async def task() -> int | None:
        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeBaseEntry)
                .where(KnowledgeBaseEntry.category == "weather")
            )
            return int(count) if count is not None else None

    return run(task())


@app.task(name="weather.evaluate")
def evaluate(
    weather: dict[str, Any], title: str, mode: Mode, engine: Engine = "rules"
) -> dict[str, Any]:
    async def task() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            return await explain(
                session, Weather.model_validate(weather), title, mode, engine, True
            )

    return run(task())
