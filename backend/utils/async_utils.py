"""Small asynchronous control-flow helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Retry an async operation and re-raise its last exception."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    def decorator(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, max_attempts + 1):
                try:
                    return await function(*args, **kwargs)
                except Exception:
                    if attempt == max_attempts:
                        raise
                    await asyncio.sleep(delay)
            raise RuntimeError("unreachable")

        return wrapped

    return decorator
