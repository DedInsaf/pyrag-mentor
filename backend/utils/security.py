"""Password hashing and JWT helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt  # type: ignore[import-untyped]

from backend.core.config import get_settings

logger = logging.getLogger(__name__)
_BCRYPT_MAX_BYTES = 72
_CLAIM_TYPES = (str, int, bool)


def _encode_password(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password exceeds {_BCRYPT_MAX_BYTES} bytes when UTF-8 encoded"
        )
    return encoded


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            _encode_password(plain_password), hashed_password.encode("utf-8")
        )
    except (TypeError, ValueError):
        logger.warning("Password verification failed")
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    settings = get_settings()
    claims = dict(data)
    for key, value in claims.items():
        if not isinstance(value, _CLAIM_TYPES):
            raise TypeError(
                f"JWT claim '{key}' has unsupported type {type(value).__name__}"
            )
    now = datetime.now(UTC)
    claims.setdefault("iat", now)
    claims["exp"] = now + (
        expires_delta or timedelta(minutes=settings.jwt_expiration_minutes)
    )
    return cast(
        str,
        jwt.encode(
            claims,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        ),
    )


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return cast(
            dict[str, Any],
            jwt.decode(
                token,
                settings.jwt_secret_key.get_secret_value(),
                algorithms=[settings.jwt_algorithm],
            ),
        )
    except JWTError as error:
        logger.warning("JWT decode failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
