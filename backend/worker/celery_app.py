import os

from celery import Celery  # type: ignore[import-untyped]

from backend.core.config import get_settings

url = get_settings().redis_url
app = Celery("weather", broker=url, backend=url, include=["backend.worker.tasks"])
app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    result_expires=3600,
    beat_schedule={
        "expire-weather-cache": {"task": "weather.clear_cache", "schedule": 3600},
        **(
            {"weather-index-refresh": {"task": "weather.index", "schedule": 86400}}
            if os.getenv("WEATHER_QDRANT_URL")
            else {}
        ),
    },
)
