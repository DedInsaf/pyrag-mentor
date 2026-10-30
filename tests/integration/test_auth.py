"""End-to-end authentication tests with an isolated SQLite database."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.api.main import create_app
from backend.core.config import Settings
from backend.db.models import Base, User
from backend.db.session import get_async_session
from backend.utils.security import create_access_token


class AuthTestContext(NamedTuple):
    client: TestClient
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
def auth_context(tmp_path: Path) -> Generator[AuthTestContext]:
    database_path = tmp_path / "auth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    async def override_session() -> AsyncGenerator[AsyncSession]:
        async with sessions() as session:
            yield session

    app = create_app(Settings(log_dir=tmp_path))
    app.dependency_overrides[get_async_session] = override_session
    with TestClient(app) as client:
        yield AuthTestContext(client, sessions)
    asyncio.run(engine.dispose())


def registration_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "email": "alice@example.com",
        "username": "alice",
        "password": "StrongPass1",
        "full_name": "Alice Student",
    }
    payload.update(overrides)
    return payload


def test_register_hashes_password_and_returns_token(
    auth_context: AuthTestContext,
) -> None:
    response = auth_context.client.post("/auth/register", json=registration_payload())
    assert response.status_code == 201
    assert response.json()["access_token"]

    async def get_user() -> User:
        async with auth_context.sessions() as session:
            return (await session.execute(select(User))).scalar_one()

    user = asyncio.run(get_user())
    assert user.hashed_password != "StrongPass1"
    assert user.hashed_password.startswith("$2")


def test_register_rejects_duplicate_email(auth_context: AuthTestContext) -> None:
    assert (
        auth_context.client.post(
            "/auth/register", json=registration_payload()
        ).status_code
        == 201
    )
    response = auth_context.client.post(
        "/auth/register",
        json=registration_payload(username="another"),
    )
    assert response.status_code == 409


def test_register_rejects_password_over_72_bytes(
    auth_context: AuthTestContext,
) -> None:
    response = auth_context.client.post(
        "/auth/register",
        json=registration_payload(password="Я" * 37 + "A1"),
    )
    assert response.status_code == 422


def test_login_and_me(auth_context: AuthTestContext) -> None:
    auth_context.client.post("/auth/register", json=registration_payload())
    login = auth_context.client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "StrongPass1"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    profile = auth_context.client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == "alice@example.com"
    assert "hashed_password" not in profile.json()


def test_me_without_token_is_401(auth_context: AuthTestContext) -> None:
    assert auth_context.client.get("/auth/me").status_code == 401


def test_me_for_missing_user_is_404(auth_context: AuthTestContext) -> None:
    token = create_access_token({"sub": "missing-user", "role": "user"})
    response = auth_context.client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_login_with_wrong_password_is_401(auth_context: AuthTestContext) -> None:
    auth_context.client.post("/auth/register", json=registration_payload())
    response = auth_context.client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "WrongPass1"},
    )
    assert response.status_code == 401


def test_inactive_user_cannot_login(auth_context: AuthTestContext) -> None:
    auth_context.client.post("/auth/register", json=registration_payload())

    async def deactivate() -> None:
        async with auth_context.sessions() as session:
            await session.execute(
                update(User)
                .where(User.email == "alice@example.com")
                .values(is_active=False)
            )
            await session.commit()

    asyncio.run(deactivate())
    response = auth_context.client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "StrongPass1"},
    )
    assert response.status_code == 403
