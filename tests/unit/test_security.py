"""Password and JWT security tests."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from backend.utils.security import (
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_is_bcrypt_and_verifies() -> None:
    hashed = get_password_hash("StrongPass1")
    assert hashed.startswith("$2")
    assert verify_password("StrongPass1", hashed)
    assert not verify_password("WrongPass1", hashed)


def test_password_over_72_bytes_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_password_hash("Я" * 37)


def test_verify_password_over_72_bytes_returns_false() -> None:
    hashed = get_password_hash("StrongPass1")
    assert not verify_password("A" * 73, hashed)


def test_jwt_round_trip() -> None:
    token = create_access_token({"sub": "user-1", "role": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "admin"
    assert payload["exp"] > payload["iat"]


def test_expired_jwt_is_rejected() -> None:
    token = create_access_token({"sub": "user-1"}, timedelta(seconds=-1))
    with pytest.raises(HTTPException) as error:
        decode_token(token)
    assert error.value.status_code == 401


def test_non_scalar_claim_is_rejected() -> None:
    with pytest.raises(TypeError):
        create_access_token({"sub": ["not", "scalar"]})
