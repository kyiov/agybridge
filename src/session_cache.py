"""
Session Credential Cache (Credential Affinity)
Binds conversational sessions to the same credential to maximize upstream Google prompt cache hits.

Dual Backends:
- Redis (optional): Enabled when REDIS_URL is configured
- In-memory (default): Local process dictionary with TTL expiration
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional

from log import log

# Session binding TTL (seconds)
SESSION_BINDING_TTL = 3600

_KEY_PREFIX = "agybridge:sess:"

_redis_client = None
_memory_store: Dict[str, tuple] = {}
_memory_lock = asyncio.Lock()
_MEMORY_MAX_ENTRIES = 50000


def _now() -> float:
    return time.time()


def _get_client():
    return _redis_client


async def init_redis(redis_url: str) -> bool:
    """Initialize Redis connection for session cache. Falls back to in-memory on failure."""
    global _redis_client
    if not redis_url:
        return False
    try:
        import redis.asyncio as redis_aiolib

        client = redis_aiolib.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )
        await client.ping()
        _redis_client = client
        log.info("Session credential cache connected to Redis")
        return True
    except Exception as e:
        log.warning(f"Redis connection failed, falling back to memory store: {e}")
        _redis_client = None
        return False


async def close() -> None:
    """Close Redis connection on server shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
    _memory_store.clear()


def derive_session_key(model_name: str, gemini_request: Dict[str, Any]) -> Optional[str]:
    """
    Derive session key from normalized Gemini request:
    hash(model + systemInstruction or first user turn)
    """
    if not isinstance(gemini_request, dict):
        return None

    model_part = model_name if isinstance(model_name, str) else ""

    anchor = None
    system_instruction = gemini_request.get("systemInstruction")
    if isinstance(system_instruction, dict):
        parts = system_instruction.get("parts")
        if isinstance(parts, list) and parts:
            anchor = _stable_json(parts)

    if anchor is None:
        contents = gemini_request.get("contents")
        if isinstance(contents, list):
            for content in contents:
                if isinstance(content, dict) and content.get("role") == "user":
                    parts = content.get("parts")
                    if isinstance(parts, list) and parts:
                        anchor = _stable_json(parts)
                        break

    if anchor is None:
        return None

    digest = hashlib.sha256(f"{model_part}|{anchor}".encode("utf-8")).hexdigest()
    return f"auto:{digest[:32]}"


def _stable_json(value: Any) -> Optional[str]:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


async def get_session_binding(session_key: str) -> Optional[str]:
    """Query credential email bound to session. Refreshes TTL on hit."""
    if not session_key:
        return None

    client = _get_client()
    if client is not None:
        redis_key = f"{_KEY_PREFIX}{session_key}"
        try:
            raw = await client.get(redis_key)
            if raw is None:
                return None
            await client.expire(redis_key, SESSION_BINDING_TTL)
            return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        except Exception as e:
            log.warning(f"Failed to query Redis session binding: {e}")

    return await _memory_get(session_key)


async def set_session_binding(session_key: str, email: str) -> None:
    """Write or update session credential binding."""
    if not session_key or not email:
        return

    client = _get_client()
    if client is not None:
        try:
            await client.setex(
                f"{_KEY_PREFIX}{session_key}", SESSION_BINDING_TTL, email
            )
        except Exception as e:
            log.warning(f"Failed to set Redis session binding: {e}")

    await _memory_set(session_key, email)


async def delete_session_binding(session_key: str) -> None:
    """Clear session binding if credential becomes unavailable."""
    if not session_key:
        return

    client = _get_client()
    if client is not None:
        try:
            await client.delete(f"{_KEY_PREFIX}{session_key}")
        except Exception as e:
            log.warning(f"Failed to delete Redis session binding: {e}")

    async with _memory_lock:
        _memory_store.pop(session_key, None)


async def _memory_get(session_key: str) -> Optional[str]:
    async with _memory_lock:
        entry = _memory_store.get(session_key)
        if not entry:
            return None
        email, expire_at = entry
        if _now() >= expire_at:
            _memory_store.pop(session_key, None)
            return None
        _memory_store[session_key] = (email, _now() + SESSION_BINDING_TTL)
        return email


async def _memory_set(session_key: str, email: str) -> None:
    async with _memory_lock:
        if len(_memory_store) >= _MEMORY_MAX_ENTRIES:
            _cleanup_expired_locked()
        if len(_memory_store) >= _MEMORY_MAX_ENTRIES:
            sorted_items = sorted(_memory_store.items(), key=lambda kv: kv[1][1])
            for k, _ in sorted_items[: len(sorted_items) // 2]:
                _memory_store.pop(k, None)
        _memory_store[session_key] = (email, _now() + SESSION_BINDING_TTL)


def _cleanup_expired_locked() -> None:
    now = _now()
    expired = [k for k, (_, exp) in _memory_store.items() if now >= exp]
    for k in expired:
        _memory_store.pop(k, None)


def memory_store_size() -> int:
    return len(_memory_store)
