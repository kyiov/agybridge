"""
Usage Logging Service: usage_log table persistence and token extraction
- record_usage_log: Persist an access log entry without throwing exceptions
- extract_usage_tokens: Extract usageMetadata token counters from Gemini responses and streaming chunks
"""

import time
import uuid
from typing import Any, Dict, Optional

import config
from log import log

from src.storage.database import get_database


def new_request_id() -> str:
    """Generate short random request ID."""
    return uuid.uuid4().hex[:16]


def extract_usage_tokens(source: Any) -> Dict[str, int]:
    """
    Extract token usage metrics from Gemini response structures.

    Compatible with:
    - Non-streaming: {"usageMetadata": {...}} or {"response": {"usageMetadata": {...}}}
    - Streaming chunks: usageMetadata within SSE data strings (typically final chunk)
    - Interactions API v1internal format (total_input_tokens / total_output_tokens, etc.)
    """
    prompt_tokens = completion_tokens = total_tokens = cached_tokens = 0

    if isinstance(source, (str, bytes)):
        try:
            text = source.decode("utf-8") if isinstance(source, bytes) else source
            if text.startswith("data: "):
                text = text[len("data: "):].strip()
            if not text or text == "[DONE]":
                return {}
            source = __import__("json").loads(text)
        except Exception:
            return {}

    if not isinstance(source, dict):
        return {}

    metadata = source.get("usageMetadata")
    if not isinstance(metadata, dict):
        response = source.get("response")
        if isinstance(response, dict):
            metadata = response.get("usageMetadata")
    if not isinstance(metadata, dict):
        return {}

    def _first_int(*keys: str) -> int:
        for key in keys:
            value = metadata.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return 0

    prompt_tokens = _first_int("promptTokenCount", "total_input_tokens", "input_tokens")
    reasoning_tokens = _first_int("thoughtsTokenCount", "total_thought_tokens")
    candidates_tokens = _first_int("candidatesTokenCount", "total_output_tokens")
    completion_tokens = candidates_tokens + reasoning_tokens
    total_tokens = _first_int("totalTokenCount", "total_tokens") or (prompt_tokens + completion_tokens)

    cached_tokens = _first_int(
        "cachedContentTokenCount",
        "cached_content_token_count",
        "total_cached_tokens",
        "cached_tokens",
        "cache_read_input_tokens",
    )
    if not cached_tokens:
        for details_key in ("prompt_tokens_details", "input_tokens_details"):
            details = metadata.get(details_key)
            if isinstance(details, dict):
                value = details.get("cached_tokens")
                if value is not None:
                    try:
                        cached_tokens = int(value)
                    except (TypeError, ValueError):
                        cached_tokens = 0
                    break

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
    }


async def record_usage_log(entry: Dict[str, Any]) -> None:
    """
    Persist a single request usage entry. Failures are logged without blocking requests.
    """
    try:
        if not await config.get_usage_log_enabled():
            return

        database = await get_database()
        entry = {**entry, "created_at": entry.get("created_at") or time.time()}
        await database.insert_usage_log(entry)
    except Exception as e:
        log.debug(f"Failed to record usage log: {e}")


async def clear_usage_logs(days: int) -> int:
    """Clear usage logs older than N days and return deleted record count."""
    database = await get_database()
    cutoff = time.time() - days * 86400
    return await database.delete_usage_logs_before(cutoff)
