"""Retry decorator behavior."""

import pytest

from backend.utils.async_utils import retry


async def test_retry_eventually_returns() -> None:
    calls = 0

    @retry(max_attempts=3, delay=0)
    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert await flaky() == "ok"
    assert calls == 3


async def test_retry_reraises_last_error() -> None:
    @retry(max_attempts=2, delay=0)
    async def broken() -> None:
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        await broken()


def test_retry_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError):
        retry(max_attempts=0)
