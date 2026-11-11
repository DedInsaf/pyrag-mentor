"""Forecast retrieval and photo rendering for the same location."""

import hashlib
import io
import os
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageOps
from pydantic import BaseModel, Field

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
VARIABLES = (
    "temperature_2m,precipitation_probability,precipitation,"
    "weather_code,cloud_cover,is_day"
)
MAX_PHOTO = 8 * 1024 * 1024


class Weather(BaseModel):
    time: datetime
    temperature_2m: float
    precipitation_probability: int = Field(ge=0, le=100)
    precipitation: float = Field(ge=0)
    weather_code: int
    cloud_cover: int = Field(ge=0, le=100)
    is_day: bool

    @property
    def condition(self) -> str:
        code = self.weather_code
        if code == 0:
            return "ясно"
        if code <= 3:
            return "облачно"
        if code in (45, 48):
            return "туман"
        if code in (71, 73, 75, 77, 85, 86):
            return "снег"
        if code >= 95:
            return "гроза"
        return "дождь"


async def forecast(latitude: float, longitude: float, hours: int) -> Weather:
    target = (datetime.now(UTC) + timedelta(hours=hours)).replace(
        minute=0, second=0, microsecond=0
    )
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": VARIABLES,
                "timezone": "GMT",
                "timeformat": "unixtime",
                "forecast_days": 3,
            },
        )
        response.raise_for_status()
        hourly = response.json()["hourly"]
    index = hourly["time"].index(int(target.timestamp()))
    return Weather(
        time=target, **{key: hourly[key][index] for key in VARIABLES.split(",")}
    )


def clean_photo(data: bytes) -> bytes:
    if len(data) > MAX_PHOTO:
        raise ValueError("Максимальный размер фото — 8 МБ")
    with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as source:
        if source.width * source.height > 24_000_000:
            raise ValueError("Максимальное разрешение — 24 мегапикселя")
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1280, 1280))
        return jpeg(image)


def jpeg(image: Image.Image) -> bytes:
    output = io.BytesIO()
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    clean.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


def render_preview(photo: bytes, weather: Weather) -> bytes:
    """Apply weather effects while retaining the geometry of the source."""
    image = Image.open(io.BytesIO(photo)).convert("RGB")
    condition = weather.condition
    night = 0.48 if not weather.is_day else 1.0
    image = ImageEnhance.Color(image).enhance(1 - weather.cloud_cover * 0.004)
    image = ImageEnhance.Brightness(image).enhance(
        night * (1 - weather.cloud_cover * 0.0025)
    )
    if condition == "туман":
        image = Image.blend(image, Image.new("RGB", image.size, "#bcc9cf"), 0.37)
    if condition in {"дождь", "снег", "гроза"}:
        rng = random.Random(hashlib.sha256(photo).digest())
        width, height = image.size
        draw = ImageDraw.Draw(image, "RGBA")
        amount = min(650, 70 + round(weather.precipitation * 80))
        for _ in range(amount):
            x, y = rng.randrange(width), rng.randrange(height)
            size = rng.randrange(1, 4)
            if condition == "снег":
                draw.ellipse(
                    (x, y, x + size * 2, y + size * 2), fill=(245, 250, 255, 125)
                )
            else:
                draw.line((x, y, x - size * 2, y + size * 8), fill=(195, 220, 242, 90))
    return jpeg(image)


def render_ai(photo: bytes, weather: Weather) -> bytes:
    """Optional hosted image editing, explicitly selected by the user."""
    from huggingface_hub import InferenceClient

    from backend.core.config import get_settings

    token = get_settings().hf_token
    if not token:
        raise ValueError("Настройте HF_TOKEN для AI-обработки")
    client = InferenceClient(
        provider="fal-ai", api_key=token.get_secret_value(), timeout=90
    )
    prompt = (
        "Edit only lighting and weather on this exact street photo. Preserve framing, "
        "buildings, objects, geometry and viewpoint. Produce a realistic photograph. "
        f"Weather in Russian: {weather.condition}; clouds {weather.cloud_cover}%; "
        f"precipitation {weather.precipitation} mm; daylight={weather.is_day}."
    )
    image: Any = client.image_to_image(
        photo,
        prompt=prompt,
        model=os.getenv("WEATHER_IMAGE_MODEL", "black-forest-labs/FLUX.2-dev"),
    )
    return clean_photo(jpeg(image.convert("RGB")))
