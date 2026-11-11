"""Weather memory retrieval with lexical and vector ranking."""

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import KnowledgeBaseEntry

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)
COLLECTION = "weather_memory_v1"


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


@lru_cache(maxsize=1)
def embedding_model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    return cast(
        "SentenceTransformer",
        SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ),
    )


def embed(texts: list[str]) -> list[list[float]]:
    return cast(
        list[list[float]],
        embedding_model().encode(texts, normalize_embeddings=True).tolist(),
    )


@asynccontextmanager
async def connect(url: str, request_timeout: int) -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(url=url, timeout=request_timeout)
    try:
        yield client
    finally:
        await client.close()


def point_id(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"weather-memory:{key}"))


def fusion(*rankings: list[str], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking)):
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank + 1)
    return sorted(scores, key=scores.__getitem__, reverse=True)


class WeatherIndex:
    def __init__(self) -> None:
        self.keys: tuple[str, ...] = ()
        self.bm25: Any = None

    async def search(
        self, session: AsyncSession, query: str, hybrid: bool
    ) -> list[str]:
        entries = (
            await session.scalars(
                select(KnowledgeBaseEntry)
                .where(KnowledgeBaseEntry.category == "weather")
                .order_by(KnowledgeBaseEntry.id)
            )
        ).all()
        keys = tuple(entry.id for entry in entries)
        if not keys:
            return []
        if self.keys != keys or self.bm25 is None:
            self.bm25 = BM25Okapi([tokens(entry.content) for entry in entries])
            self.keys = keys
        scores = self.bm25.get_scores(tokens(query))
        lexical = [
            keys[i]
            for i in sorted(range(len(keys)), key=lambda i: scores[i], reverse=True)
            if scores[i] > 0
        ][:12]
        vector: list[str] = []
        url = os.getenv("WEATHER_QDRANT_URL")
        if hybrid and url:
            try:
                async with connect(url, request_timeout=3) as client:
                    if await client.collection_exists(COLLECTION):
                        result = await client.query_points(
                            COLLECTION,
                            query=(await asyncio.to_thread(embed, [query]))[0],
                            limit=12,
                            with_payload=True,
                        )
                        vector = [
                            str(p.payload["entry"])
                            for p in result.points
                            if p.payload and "entry" in p.payload
                        ]
            except Exception:
                logger.warning("Qdrant weather search unavailable; using BM25")
        items = {entry.id: entry.answer for entry in entries}
        return [items[key] for key in fusion(lexical, vector) if key in items][:4]


index = WeatherIndex()


async def reindex(session: AsyncSession, url: str) -> int:
    entries = (
        await session.scalars(
            select(KnowledgeBaseEntry).where(KnowledgeBaseEntry.category == "weather")
        )
    ).all()
    async with connect(url, request_timeout=20) as client:
        if not await client.collection_exists(COLLECTION):
            await client.create_collection(
                COLLECTION,
                vectors_config=models.VectorParams(
                    size=384,
                    distance=models.Distance.COSINE,
                ),
            )
        for start in range(0, len(entries), 64):
            batch = entries[start : start + 64]
            vectors = await asyncio.to_thread(embed, [entry.content for entry in batch])
            await client.upsert(
                COLLECTION,
                points=[
                    models.PointStruct(
                        id=point_id(entry.id),
                        vector=vector,
                        payload={"entry": entry.id},
                    )
                    for entry, vector in zip(batch, vectors, strict=True)
                ],
            )
    return len(entries)
