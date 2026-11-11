"""Registration, photo forecast, caching, contributions and moderation."""

import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.main import create_app
from backend.api.routes import weather as routes
from backend.core.config import Settings
from backend.data.weather import Weather
from backend.db.models import Base, User
from backend.db.session import get_async_session
from backend.db.weather import WeatherReview
from backend.utils.security import create_access_token


async def test_weather_journey(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolated.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(WeatherReview(id="review", question="Казань снег", draft="Ошибка"))
        db.add(
            User(
                id="editor",
                email="editor@example.org",
                username="editor",
                hashed_password="unused",
                role="editor",
            )
        )
        await db.commit()

    async def session() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db

    async def forecast(*args: Any) -> Weather:
        return Weather(
            time=datetime(2026, 1, 1, 11, tzinfo=UTC),
            temperature_2m=-3,
            precipitation_probability=91,
            precipitation=1.3,
            weather_code=73,
            cloud_cover=95,
            is_day=True,
        )

    monkeypatch.setattr(routes, "forecast", forecast)
    app = create_app(Settings(log_dir=tmp_path))
    app.dependency_overrides[get_async_session] = session
    editor = {"Authorization": "Bearer " + create_access_token({"sub": "editor"})}
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), "#305030").save(buffer, "PNG")
    files = {"file": ("park.png", buffer.getvalue(), "image/png")}
    data = {"latitude": 55.79, "longitude": 49.12, "title": "Парк", "hours": 4}
    client = TestClient(app)
    try:
        credentials = {"email": "member@example.org", "password": "StrongPass1"}
        assert (
            client.post(
                "/auth/register", json={**credentials, "username": "member"}
            ).status_code
            == 201
        )
        login = client.post("/auth/login", json=credentials)
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert client.get("/hitl/uncertain", headers=headers).status_code == 403
        review_url = "/hitl/uncertain/review/confirm"
        correction = {"text": "При снегопаде видимость может ухудшиться."}
        response = client.post(review_url, headers=editor, json=correction)
        assert response.json() == {"status": "confirmed", "memory_inserted": True}
        assert (
            client.post(review_url, headers=editor, json=correction).status_code == 404
        )
        assert client.get("/hitl/stats", headers=editor).json()["confirmed"] == 1
        import_url = "/weather-admin/glossary/import-csv"
        csv = {"file": ("terms.csv", "title,text\nснег,Видимость снижается\n".encode())}
        assert client.post(import_url, headers=headers, files=csv).status_code == 403
        assert client.post(import_url, headers=editor, files=csv).json()["added"] == 1
        assert client.post(import_url, headers=editor, files=csv).json()["added"] == 0
        endpoint = "/weather/forecast"
        assert client.post(endpoint, data=data, files=files).status_code == 401
        assert client.post(endpoint, headers=headers, data=data).status_code == 422
        first = client.post(endpoint, headers=headers, data=data, files=files)
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["condition"] == "снег"
        assert result["image"] != result["original"]
        assert result["cached"] is False
        assert client.post(endpoint, headers=headers, data=data, files=files).json()[
            "cached"
        ]
        assert (
            client.post("/weather/batch", headers=headers, json=[data]).json()[0][
                "condition"
            ]
            == "снег"
        )
        upload = client.post(
            "/weather/places",
            headers=headers,
            data={**data, "publish": True},
            files=files,
        )
        assert upload.status_code == 201, upload.text
        photo = upload.json()
        assert client.get("/weather/places").json() == []
        assert (
            client.get("/hitl/uncertain", headers=editor).json()["photos"][0]["id"]
            == photo["id"]
        )
        url = f'/hitl/photos/{photo["id"]}'
        assert client.get(f"{url}/image", headers=editor).content.startswith(
            b"\xff\xd8"
        )
        assert client.post(f"{url}/approved", headers=editor).status_code == 200
        assert client.post(f"{url}/approved", headers=editor).status_code == 404
        assert (
            client.get("/weather/contributions/me", headers=headers).json()["points"]
            == 10
        )
        assert client.get("/weather/places").json()[0]["title"] == "Парк"
        multi = client.post(
            "/weather/multi",
            headers=headers,
            json={
                "place_id": photo["id"],
                "hours": [3, 6, 3],
            },
        )
        assert multi.status_code == 200
        assert [row["hours"] for row in multi.json()] == [3, 6]
        assert client.get(f'/weather/places/{photo["id"]}/image').status_code == 200
        assert (
            client.post(
                endpoint, headers=headers, data={"place_id": photo["id"]}
            ).status_code
            == 200
        )
    finally:
        client.close()
        await engine.dispose()
