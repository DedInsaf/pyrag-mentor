"""Editor tools for maintaining the weather glossary and archive memory."""

import asyncio
import csv
import hashlib
import io
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import SessionDependency, require_editor
from backend.db.models import GlossaryEntry, KnowledgeBaseEntry, ResponseCache

router = APIRouter(prefix="/weather-admin", dependencies=[Depends(require_editor)])
Library = Literal["glossary", "memory"]


class Entry(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="internal:moderation", min_length=1, max_length=500)


async def enqueue_reindex() -> None:
    if os.getenv("WEATHER_QDRANT_URL"):
        from backend.worker.tasks import index_weather

        try:
            await asyncio.to_thread(index_weather.delay)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Weather reindex could not be queued")


async def invalidate(db: AsyncSession) -> None:
    await db.execute(delete(ResponseCache).where(ResponseCache.category == "weather"))


async def insert_entries(db: AsyncSession, kind: Library, entries: list[Entry]) -> int:
    table = GlossaryEntry if kind == "glossary" else KnowledgeBaseEntry
    insert = (
        sqlite_insert if db.bind and db.bind.dialect.name == "sqlite" else pg_insert
    )
    values = []
    for row in entries:
        key = hashlib.sha256(f"{row.title}\0{row.text}".encode()).hexdigest()
        common = {"id": key, "source_url": row.source, "category": "weather"}
        if kind == "glossary":
            values.append({**common, "term": row.title, "definition": row.text})
        else:
            values.append(
                {
                    **common,
                    "question": row.title,
                    "content": row.title,
                    "answer": row.text,
                }
            )
    added = 0
    for start in range(0, len(values), 100):
        stmt = (
            insert(table)
            .values(values[start : start + 100])
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(table.id)
        )
        added += len((await db.scalars(stmt)).all())
    return added


async def finish(db: AsyncSession, kind: Library, changed: int) -> None:
    if changed:
        await invalidate(db)
    await db.commit()
    if changed and kind == "memory":
        await enqueue_reindex()


@router.get("/cache/stats")
async def cache_stats(db: SessionDependency) -> dict[str, int]:
    count, hits = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(ResponseCache.hits), 0),
            ).where(ResponseCache.category == "weather")
        )
    ).one()
    return {"entries": count, "hits": hits}


@router.delete("/cache")
async def clear_cache(db: SessionDependency) -> dict[str, str]:
    await invalidate(db)
    await db.commit()
    return {"status": "cleared"}


@router.post("/{kind}", status_code=201)
async def add(kind: Library, entry: Entry, db: SessionDependency) -> dict[str, int]:
    added = await insert_entries(db, kind, [entry])
    await finish(db, kind, added)
    return {"added": added}


@router.post("/{kind}/import-csv", status_code=201)
async def import_csv(
    kind: Library, file: UploadFile, db: SessionDependency
) -> dict[str, int]:
    limit = 2 * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, "CSV должен быть не больше 2 МБ")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if not {"title", "text"}.issubset(reader.fieldnames or []):
            raise ValueError("Expected title,text columns")
        entries = [Entry.model_validate(row) for row in reader]
    except (UnicodeError, csv.Error, ValidationError, ValueError) as exc:
        raise HTTPException(
            422, "Ожидается CSV UTF-8 со столбцами title,text,source"
        ) from exc
    added = await insert_entries(db, kind, entries)
    await finish(db, kind, added)
    return {"added": added, "rows": len(entries)}


@router.get("/{kind}")
async def library(
    kind: Library,
    db: SessionDependency,
    q: str = "",
) -> list[dict[str, Any]]:
    if kind == "glossary":
        cards = await db.scalars(
            select(GlossaryEntry)
            .where(
                GlossaryEntry.category == "weather",
                GlossaryEntry.term.icontains(q[:120], autoescape=True),
            )
            .order_by(GlossaryEntry.id)
            .limit(100)
        )
        return [
            {
                "id": card.id,
                "title": card.term,
                "text": card.definition,
                "source": card.source_url,
            }
            for card in cards
        ]
    memory = await db.scalars(
        select(KnowledgeBaseEntry)
        .where(
            KnowledgeBaseEntry.category == "weather",
            KnowledgeBaseEntry.question.icontains(q[:120], autoescape=True),
        )
        .order_by(KnowledgeBaseEntry.id)
        .limit(100)
    )
    return [
        {
            "id": row.id,
            "title": row.question,
            "text": row.answer,
            "source": row.source_url,
        }
        for row in memory
    ]


@router.delete("/{kind}/{entry_id}")
async def remove(kind: Library, entry_id: str, db: SessionDependency) -> dict[str, str]:
    table = GlossaryEntry if kind == "glossary" else KnowledgeBaseEntry
    result = await db.scalar(
        delete(table)
        .where(table.id == entry_id, table.category == "weather")
        .returning(table.id)
    )
    if result is None:
        raise HTTPException(404)
    await finish(db, kind, 1)
    return {"status": "deleted"}


@router.post("/feedback/correction", status_code=201)
async def save_correction(entry: Entry, db: SessionDependency) -> dict[str, str]:
    added = await insert_entries(db, "memory", [entry])
    await finish(db, "memory", added)
    return {"status": "saved" if added else "skipped"}
