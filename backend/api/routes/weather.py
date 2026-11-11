"""Forecasts, contributed photos, and moderation."""

import asyncio
import base64
import hashlib
import logging
import os
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from backend.api.deps import CurrentUser, SessionDependency, require_editor
from backend.api.routes.weather_admin import Entry, finish, insert_entries
from backend.data.weather import (
    MAX_PHOTO,
    clean_photo,
    forecast,
    render_ai,
    render_preview,
)
from backend.db.models import User
from backend.db.session import AsyncSessionLocal
from backend.db.weather import PlacePhoto, WeatherReview
from backend.services.weather import Engine, EngineUnavailable, Mode, explain

router = APIRouter()
logger = logging.getLogger(__name__)
EditorUser = Annotated[User, Depends(require_editor)]
Latitude = Annotated[float, Form(ge=-90, le=90)]
Longitude = Annotated[float, Form(ge=-180, le=180)]
Title = Annotated[str, Form(min_length=1, max_length=120)]


async def read_photo(file: UploadFile) -> bytes:
    try:
        return await asyncio.to_thread(clean_photo, await file.read(MAX_PHOTO + 1))
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            422, "Выберите корректное фото JPEG, PNG или WebP до 8 МБ"
        ) from exc


def place_metadata(photo: PlacePhoto) -> dict[str, Any]:
    return {
        "id": photo.id,
        "title": photo.title,
        "latitude": photo.latitude,
        "longitude": photo.longitude,
        "status": photo.status,
    }


@router.get("/weather/places")
async def places(db: SessionDependency, q: str = "") -> list[dict[str, Any]]:
    result = await db.scalars(
        select(PlacePhoto)
        .where(
            PlacePhoto.status == "approved",
            PlacePhoto.title.icontains(q[:120], autoescape=True),
        )
        .order_by(PlacePhoto.created.desc())
        .limit(100)
    )
    return [place_metadata(photo) for photo in result]


@router.get("/weather/places/{photo_id}/image")
async def photo_image(photo_id: str, db: SessionDependency) -> Response:
    photo = await db.get(PlacePhoto, photo_id)
    if photo is None or photo.status != "approved":
        raise HTTPException(404)
    return Response(photo.content, media_type="image/jpeg")


@router.post("/weather/places", status_code=201)
async def contribute(
    user: CurrentUser,
    db: SessionDependency,
    title: Title,
    latitude: Latitude,
    longitude: Longitude,
    file: UploadFile,
    publish: Annotated[bool, Form()],
) -> dict[str, Any]:
    if not publish or not title.strip():
        raise HTTPException(422, "Подтвердите публикацию и заполните название")
    image = await read_photo(file)
    digest = hashlib.sha256(image).hexdigest()
    existing = await db.scalar(
        select(PlacePhoto).where(
            PlacePhoto.owner == user.id,
            PlacePhoto.digest == digest,
            PlacePhoto.status.in_(["pending", "approved"]),
        )
    )
    if existing:
        return place_metadata(existing)
    photo = PlacePhoto(
        owner=user.id,
        title=title.strip(),
        latitude=latitude,
        longitude=longitude,
        content=image,
        digest=digest,
    )
    db.add(photo)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Фото уже отправлено") from exc
    return place_metadata(photo)


@router.get("/weather/contributions/me")
async def contributions(user: CurrentUser, db: SessionDependency) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(PlacePhoto)
            .where(PlacePhoto.owner == user.id)
            .order_by(PlacePhoto.created.desc())
        )
    ).all()
    approved = sum(photo.status == "approved" for photo in rows)
    return {
        "points": approved * 10,
        "photos": [place_metadata(photo) for photo in rows],
    }


@router.post("/weather/forecast")
async def visualize(
    user: CurrentUser,
    db: SessionDependency,
    latitude: Annotated[float | None, Form(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Form(ge=-180, le=180)] = None,
    hours: Annotated[int, Form(ge=1, le=48)] = 3,
    title: Title = "Локация",
    file: Annotated[UploadFile | None, File()] = None,
    place_id: Annotated[str | None, Form()] = None,
    image_engine: Annotated[Literal["preview", "ai"], Form()] = "preview",
    mode: Annotated[Mode | None, Form()] = None,
    engine: Annotated[Engine, Form()] = "rules",
    strict_engine: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    if bool(file) == bool(place_id):
        raise HTTPException(422, "Выберите одно фото или место из каталога")
    if file is not None:
        if latitude is None or longitude is None:
            raise HTTPException(422, "Укажите координаты места съёмки")
        image = await read_photo(file)
    else:
        place = await db.get(PlacePhoto, place_id)
        if place is None or place.status != "approved":
            raise HTTPException(404, "Место не найдено")
        image, title, latitude, longitude = (
            place.content,
            place.title,
            place.latitude,
            place.longitude,
        )
    selected = mode or os.getenv("EVAL_MODE", "full")
    from backend.services.weather import MODES

    if selected not in MODES:
        raise HTTPException(422, "Неизвестный режим")
    try:
        weather = await forecast(latitude, longitude, hours)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "Погодный сервис временно недоступен") from exc
    try:
        render = render_ai if image_engine == "ai" else render_preview
        result = await asyncio.to_thread(render, image, weather)
    except Exception as exc:
        logger.warning("Weather image rendering failed: %s", type(exc).__name__)
        raise HTTPException(
            503,
            "Обработка фото недоступна. Проверьте настройки или выберите визуализацию.",
        ) from exc
    try:
        details = await explain(
            db, weather, title, cast(Mode, selected), engine, strict_engine
        )
    except EngineUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        **details,
        "forecast": weather.model_dump(mode="json"),
        "condition": weather.condition,
        "image_engine": image_engine,
        "original": base64.b64encode(image).decode(),
        "image": base64.b64encode(result).decode(),
    }


@router.get("/hitl/uncertain")
async def pending(editor: EditorUser, db: SessionDependency) -> dict[str, Any]:
    photos = await db.scalars(
        select(PlacePhoto).where(PlacePhoto.status == "pending").limit(100)
    )
    reviews = await db.scalars(
        select(WeatherReview).where(WeatherReview.status == "pending").limit(100)
    )
    return {
        "photos": [place_metadata(photo) for photo in photos],
        "forecasts": [
            {"id": row.id, "question": row.question, "draft": row.draft}
            for row in reviews
        ],
    }


@router.get("/hitl/photos/{photo_id}/image")
async def moderation_image(
    photo_id: str, editor: EditorUser, db: SessionDependency
) -> Response:
    photo = await db.get(PlacePhoto, photo_id)
    if photo is None:
        raise HTTPException(404)
    return Response(photo.content, media_type="image/jpeg")


@router.post("/hitl/photos/{photo_id}/{decision}")
async def moderate_photo(
    photo_id: str,
    decision: Literal["approved", "rejected"],
    editor: EditorUser,
    db: SessionDependency,
) -> dict[str, str]:
    changed = await db.scalar(
        update(PlacePhoto)
        .where(
            PlacePhoto.id == photo_id,
            PlacePhoto.status == "pending",
        )
        .values(status=decision)
        .returning(PlacePhoto.id)
    )
    if not changed:
        raise HTTPException(404)
    await db.commit()
    return {"status": decision}


class Correction(BaseModel):
    text: str = Field(min_length=5, max_length=4000)


@router.post("/hitl/uncertain/{review_id}/confirm")
async def confirm(
    review_id: str,
    correction: Correction,
    editor: EditorUser,
    db: SessionDependency,
) -> dict[str, Any]:
    question = await db.scalar(
        update(WeatherReview)
        .where(
            WeatherReview.id == review_id,
            WeatherReview.status == "pending",
        )
        .values(status="confirmed")
        .returning(WeatherReview.question)
    )
    if question is None:
        raise HTTPException(404)
    inserted = await insert_entries(
        db, "memory", [Entry(title=question, text=correction.text)]
    )
    await finish(db, "memory", inserted)
    return {"status": "confirmed", "memory_inserted": bool(inserted)}


@router.post("/hitl/uncertain/{review_id}/reject")
async def reject(
    review_id: str, editor: EditorUser, db: SessionDependency
) -> dict[str, str]:
    changed = await db.scalar(
        update(WeatherReview)
        .where(
            WeatherReview.id == review_id,
            WeatherReview.status == "pending",
        )
        .values(status="rejected")
        .returning(WeatherReview.id)
    )
    if not changed:
        raise HTTPException(404)
    await db.commit()
    return {"status": "rejected"}


@router.get("/hitl/stats")
async def stats(editor: EditorUser, db: SessionDependency) -> dict[str, int]:
    rows = await db.execute(
        select(WeatherReview.status, func.count()).group_by(WeatherReview.status)
    )
    return {
        "pending": 0,
        "confirmed": 0,
        "rejected": 0,
        **{status: count for status, count in rows},
    }


class BatchLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    hours: int = Field(ge=1, le=48)


@router.post("/weather/batch")
async def batch(
    items: Annotated[list[BatchLocation], Body(min_length=1, max_length=50)],
    user: CurrentUser,
) -> list[dict[str, Any]]:
    async def get_one(item: BatchLocation) -> dict[str, Any]:
        try:
            result = await forecast(item.latitude, item.longitude, item.hours)
            return {
                "forecast": result.model_dump(mode="json"),
                "condition": result.condition,
            }
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return {"error": "Прогноз недоступен"}

    result = []
    for offset in range(0, len(items), 4):
        result.extend(
            await asyncio.gather(
                *(get_one(item) for item in items[offset : offset + 4])
            )
        )
    return result


class EnsembleLocation(BatchLocation):
    title: str = Field(default="Локация", min_length=1, max_length=120)
    engines: list[Engine] = Field(min_length=2, max_length=4)


@router.post("/weather/ensemble")
async def ensemble(item: EnsembleLocation, user: CurrentUser) -> dict[str, Any]:
    engines = list(dict.fromkeys(item.engines))
    if len(engines) < 2:
        raise HTTPException(422, "Выберите минимум два разных движка")
    try:
        weather = await forecast(item.latitude, item.longitude, item.hours)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "Прогноз недоступен") from exc

    async def candidate(engine: Engine) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                async with asyncio.timeout(90):
                    return await explain(
                        session, weather, item.title, "full", engine, True
                    )
            except (EngineUnavailable, TimeoutError):
                return {"engine_used": engine, "error": "Движок недоступен"}

    variants = await asyncio.gather(*(candidate(engine) for engine in engines))
    successful = [row for row in variants if "error" not in row]
    scored = [row for row in successful if row.get("critic_score") is not None]
    best = (
        max(scored, key=lambda row: row["critic_score"])
        if scored
        else next(iter(successful), None)
    )
    return {
        "variants": variants,
        "best": best,
        "warning": None if scored else "Сопоставимые оценки критика отсутствуют",
    }
