"""
Generic HTTP Client Module
Provides unified HTTP client setup and request execution via httpx.
Stateless functional design: dynamically constructs and destroys clients per invocation.
"""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

import httpx
from fastapi import Response

from config import get_proxy_config, get_stream_read_timeout, get_request_timeout
from log import log


async def get_client_kwargs(timeout: Optional[Any] = 30.0, **kwargs) -> Dict[str, Any]:
    """Retrieve common httpx client configuration kwargs with robust connect/read timeouts."""
    if timeout is None:
        read_timeout = await get_stream_read_timeout()
        timeout_config = httpx.Timeout(
            connect=15.0,
            read=read_timeout,
            write=30.0,
            pool=15.0,
        )
    elif isinstance(timeout, (int, float)):
        timeout_config = httpx.Timeout(
            timeout=float(timeout),
            connect=15.0,
        )
    else:
        timeout_config = timeout

    client_kwargs = {"timeout": timeout_config, **kwargs}

    # Dynamically inject proxy if configured
    current_proxy_config = await get_proxy_config()
    if current_proxy_config:
        client_kwargs["proxy"] = current_proxy_config

    return client_kwargs


@asynccontextmanager
async def get_client(
    timeout: float = 30.0, **kwargs
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide configured asynchronous HTTP client context."""
    client_kwargs = await get_client_kwargs(timeout=timeout, **kwargs)

    async with httpx.AsyncClient(**client_kwargs) as client:
        yield client


@asynccontextmanager
async def get_streaming_client(
    timeout: float = None, **kwargs
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide streaming HTTP client context without premature timeout restrictions."""
    client_kwargs = await get_client_kwargs(timeout=timeout, **kwargs)

    client = httpx.AsyncClient(**client_kwargs)
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception as e:
            log.warning(f"Error closing streaming client: {e}")


async def get_async(
    url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0, **kwargs
) -> httpx.Response:
    """Execute asynchronous GET request."""
    async with get_client(timeout=timeout, **kwargs) as client:
        return await client.get(url, headers=headers)


async def post_async(
    url: str,
    data: Any = None,
    json: Any = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    **kwargs,
) -> httpx.Response:
    """Execute asynchronous POST request with hang prevention."""
    if timeout is None:
        timeout = await get_request_timeout()
    async with get_client(timeout=timeout, **kwargs) as client:
        return await client.post(url, data=data, json=json, headers=headers)


_MOCK_STREAM_429 = False

async def stream_post_async(
    url: str,
    body: Dict[str, Any],
    native: bool = False,
    headers: Optional[Dict[str, str]] = None,
    **kwargs,
):
    """Execute streaming asynchronous POST request."""
    if _MOCK_STREAM_429:
        log.warning("[MOCK] stream_post_async: returning simulated 429")
        yield Response(
            content=json.dumps({"error": {"code": 429, "message": "mock rate limit", "status": "RESOURCE_EXHAUSTED"}}),
            status_code=429,
        )
        return

    async with get_streaming_client(**kwargs) as client:
        async with client.stream("POST", url, json=body, headers=headers) as r:
            if r.status_code != 200:
                yield Response(await r.aread(), r.status_code, dict(r.headers))
                return

            if native:
                async for chunk in r.aiter_bytes():
                    yield chunk
            else:
                async for line in r.aiter_lines():
                    yield line
