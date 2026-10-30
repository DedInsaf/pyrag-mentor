"""Shared asynchronous SQLAlchemy engine and session dependency."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import get_settings

settings = get_settings()

engine_options: dict[str, Any] = {
    "echo": settings.debug or settings.database_echo,
    "pool_pre_ping": True,
}
if not settings.async_database_url.startswith("sqlite"):
    engine_options.update(pool_size=10, max_overflow=20)

async_engine = create_async_engine(settings.async_database_url, **engine_options)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Yield one async database session per FastAPI request."""

    async with AsyncSessionLocal() as session:
        yield session


get_db = get_async_session
