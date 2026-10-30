"""Event-loop-local HTTP clients for external model APIs."""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

import httpx

_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    WeakKeyDictionary()
)


def get_http_client() -> httpx.AsyncClient:
    """Return a reusable client bound to the currently running event loop."""

    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=60.0)
        _clients[loop] = client
    return client


async def close_http_client() -> None:
    """Close and remove the client associated with the current loop."""

    loop = asyncio.get_running_loop()
    client = _clients.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()
