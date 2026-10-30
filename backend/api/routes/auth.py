"""Registration, login, and current-user routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.api.deps import CurrentUser, SessionDependency
from backend.db.models import User
from backend.utils.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not 3 <= len(value) <= 64:
            raise ValueError("Username must contain 3 to 64 characters")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(char.isdigit() for char in value):
            raise ValueError("Password must contain at least one digit")
        if not any(char.isupper() for char in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str
    username: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    full_name: str | None
    role: str
    is_active: bool


def _issue_token(user: User) -> TokenResponse:
    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        role=user.role,
        username=user.username,
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    request: RegisterRequest, session: SessionDependency
) -> TokenResponse:
    email = str(request.email).lower()
    if (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    if (
        await session.execute(select(User).where(User.username == request.username))
    ).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        email=email,
        username=request.username,
        hashed_password=get_password_hash(request.password),
        full_name=request.full_name,
        role="user",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from error
    await session.refresh(user)
    logger.info("User registered: %s", user.email)
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, session: SessionDependency) -> TokenResponse:
    result = await session.execute(
        select(User).where(User.email == str(request.email).lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    logger.info("User logged in: %s", user.email)
    return _issue_token(user)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> User:
    return current_user
