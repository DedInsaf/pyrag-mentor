"""Worker tasks share one event loop and retain batch ordering."""

import asyncio
from datetime import UTC, datetime

import pytest

from backend.data.weather import Weather
from backend.worker import tasks
from backend.worker.celery_app import app


@pytest.mark.parametrize(
    "name",
    [
        "weather.index",
        "weather.clear_cache",
        "weather.batch",
        "weather.cache_stats",
        "weather.memory_stats",
        "weather.evaluate",
    ],
)
def test_registered_task(name: str) -> None:
    assert name in app.tasks


def test_worker_keeps_loop_and_shuts_down() -> None:
    async def current() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    try:
        assert tasks.run(current()) is tasks.run(current())
    finally:
        tasks.close_worker_loop()
    assert tasks._loop is None


def test_batch_returns_success_and_error_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_forecast(latitude: float, longitude: float, hours: int) -> Weather:
        if latitude == 0:
            raise ValueError
        return Weather(
            time=datetime(2026, 1, 1, tzinfo=UTC),
            temperature_2m=2,
            precipitation_probability=0,
            precipitation=0,
            weather_code=0,
            cloud_cover=0,
            is_day=True,
        )

    monkeypatch.setattr(tasks, "forecast", fake_forecast)
    try:
        result = tasks.batch_forecast(
            [
                {"latitude": 0, "longitude": 1, "hours": 3},
                {"latitude": 2, "longitude": 1, "hours": 3},
            ]
        )
        assert result[0] == {"error": "ValueError"}
        assert result[1]["condition"] == "ясно"
    finally:
        tasks.close_worker_loop()
