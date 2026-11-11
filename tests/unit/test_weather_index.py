"""Exercise Qdrant storage and retrieval with deterministic test embeddings."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.models import Base, KnowledgeBaseEntry
from backend.retrieval import weather_index as search


async def test_vector_upsert_and_lexical_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    client = AsyncQdrantClient(":memory:")

    @asynccontextmanager
    async def connect(
        url: str, request_timeout: int
    ) -> AsyncIterator[AsyncQdrantClient]:
        yield client

    @asynccontextmanager
    async def offline(
        url: str, request_timeout: int
    ) -> AsyncIterator[AsyncQdrantClient]:
        raise OSError("offline")
        yield client

    def embeddings(texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]

    monkeypatch.setattr(search, "connect", connect)
    monkeypatch.setattr(search, "embed", embeddings)
    monkeypatch.setenv("WEATHER_QDRANT_URL", "http://test.invalid")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as db:
            for key, term in enumerate(
                ("гроза", "облака", "солнце", "туман", "ливень")
            ):
                db.add(
                    KnowledgeBaseEntry(
                        id=str(key),
                        question=term,
                        content=term,
                        answer=term,
                        category="weather",
                        source_url="test",
                    )
                )
            await db.commit()
            assert await search.reindex(db, "test") == 5
            assert await search.reindex(db, "test") == 5
            assert (await client.count(search.COLLECTION)).count == 5
            index = search.WeatherIndex()
            assert len(await index.search(db, "гроза", hybrid=True)) == 4
            monkeypatch.setattr(search, "connect", offline)
            assert await index.search(db, "гроза", hybrid=True) == ["гроза"]
    finally:
        await client.close()
        await engine.dispose()
