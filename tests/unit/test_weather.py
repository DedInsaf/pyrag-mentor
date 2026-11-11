import io
from datetime import UTC, datetime, tzinfo

import httpx
import pytest
from PIL import Image

from backend.data import weather
from backend.retrieval.weather_index import fusion, point_id, tokens


def sample(code: int, day: bool = True) -> weather.Weather:
    return weather.Weather(
        time=datetime.now(UTC),
        temperature_2m=7,
        precipitation_probability=70,
        precipitation=2,
        weather_code=code,
        cloud_cover=83,
        is_day=day,
    )


@pytest.mark.parametrize(
    ("code", "condition"),
    [
        (0, "ясно"),
        (3, "облачно"),
        (45, "туман"),
        (63, "дождь"),
        (73, "снег"),
        (95, "гроза"),
    ],
)
def test_weather_render_preserves_size(code: int, condition: str) -> None:
    forecast = sample(code, False)
    assert forecast.condition == condition
    source = weather.jpeg(Image.new("RGB", (75, 30), "white"))
    result = weather.render_preview(source, forecast)
    assert Image.open(io.BytesIO(result)).size == (75, 30)
    assert result != source
    assert result == weather.render_preview(source, forecast)


def test_upload_cleaning_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Image.new("RGB", (10, 10))
    buffer = io.BytesIO()
    original.save(buffer, "JPEG", comment=b"test metadata")
    result = weather.clean_photo(buffer.getvalue())
    assert b"test metadata" not in result
    monkeypatch.setattr(weather, "MAX_PHOTO", 3)
    with pytest.raises(ValueError):
        weather.clean_photo(buffer.getvalue())


def test_rank_fusion() -> None:
    assert tokens("КАЗАНЬ, дождь!") == ["казань", "дождь"]
    assert point_id("a") == point_id("a")
    assert point_id("a") != point_id("b")
    assert fusion(["a", "b"], ["c", "b"]) == ["b", "a", "c"]


async def test_forecast_uses_selected_utc_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "Clock":
            return cls(2026, 1, 1, 15, 30, tzinfo=UTC)

    client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["latitude"] == "55.79"
        assert request.url.params["timeformat"] == "unixtime"
        hour = int(Clock(2026, 1, 1, 18, tzinfo=UTC).timestamp())
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": [hour - 3600, hour],
                    "temperature_2m": [5, 6],
                    "precipitation_probability": [0, 60],
                    "precipitation": [0, 1.5],
                    "weather_code": [0, 63],
                    "cloud_cover": [20, 40],
                    "is_day": [1, 0],
                }
            },
        )

    monkeypatch.setattr(weather, "datetime", Clock)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw),
    )
    result = await weather.forecast(55.79, 49.12, 3)
    assert result.temperature_2m == 6
    assert result.condition == "дождь"
    assert not result.is_day
