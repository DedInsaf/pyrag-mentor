"""Unit tests for the five SQLAlchemy models using SQLite in memory."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import (
    Base,
    GlossaryEntry,
    KnowledgeBaseEntry,
    ResponseCache,
    UncertainExample,
    User,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def test_all_five_tables_are_declared() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "glossaries",
        "knowledge_base",
        "uncertain_examples",
        "response_cache",
    }


def test_expected_indexes_are_declared() -> None:
    glossary_table = GlossaryEntry.__table__
    knowledge_table = KnowledgeBaseEntry.__table__
    assert isinstance(glossary_table, Table)
    assert isinstance(knowledge_table, Table)
    assert "ix_glossaries_category" in {index.name for index in glossary_table.indexes}
    assert "ix_knowledge_category" in {index.name for index in knowledge_table.indexes}


async def test_user_defaults(session: AsyncSession) -> None:
    user = User(email="user@example.com", username="student", hashed_password="hash")
    session.add(user)
    await session.commit()
    assert user.role == "user"
    assert user.is_active is True
    assert user.id


async def test_unique_user_email(session: AsyncSession) -> None:
    session.add_all(
        [
            User(email="same@example.com", username="one", hashed_password="hash"),
            User(email="same@example.com", username="two", hashed_password="hash"),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_glossary_round_trip(session: AsyncSession) -> None:
    entry = GlossaryEntry(
        id="term-list",
        term="list",
        definition="Mutable sequence",
        category="language_basics",
    )
    session.add(entry)
    await session.commit()
    found = await session.get(GlossaryEntry, "term-list")
    assert found is not None and found.definition == "Mutable sequence"


async def test_knowledge_base_round_trip(session: AsyncSession) -> None:
    entry = KnowledgeBaseEntry(
        id="kb-1",
        question="What is a list?",
        answer="A mutable sequence.",
        content="Python list documentation.",
        category="language_basics",
        source_url="https://docs.python.org/3/library/stdtypes.html#lists",
    )
    session.add(entry)
    await session.commit()
    found = (await session.execute(select(KnowledgeBaseEntry))).scalar_one()
    assert found.python_version == "3.12"


async def test_uncertain_example_defaults(session: AsyncSession) -> None:
    example = UncertainExample(input_text="question", model_output="answer")
    session.add(example)
    await session.commit()
    assert example.status == "pending"
    assert example.validation_passed is False


async def test_cache_sentinel_defaults(session: AsyncSession) -> None:
    cached = ResponseCache(input_text="q", output="a")
    session.add(cached)
    await session.commit()
    assert cached.category == "unknown"
    assert cached.parameters_hash == "unknown"
    assert cached.model_used == "unknown"
    assert cached.hits == 1
