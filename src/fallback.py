"""
Key-Based Fallback Module (Jalur Ber-Key)
Seamless fallback to official/direct API keys (e.g. Google Gemini API Key via AI Studio)
when OAuth accounts hit rate limits, expire, or hang, preventing long runs from aborting.
"""

import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi import Response
from config import (
    get_fallback_api_keys,
    get_fallback_base_url,
    get_fallback_enabled,
    get_fallback_model,
)
from log import log
from src.httpx_client import post_async, stream_post_async
from src.usage_log import (
    extract_usage_tokens,
    new_request_id,
    record_usage_log,
)

_key_index = 0


async def is_fallback_available() -> bool:
    """Check if key-based fallback is enabled and has configured keys."""
    if not await get_fallback_enabled():
        return False
    keys = await get_fallback_api_keys()
    return len(keys) > 0


async def get_next_fallback_key() -> Optional[str]:
    """Retrieve next available fallback key using round-robin rotation."""
    global _key_index
    keys = await get_fallback_api_keys()
    if not keys:
        return None
    key = keys[_key_index % len(keys)]
    _key_index = (_key_index + 1) % len(keys)
    return key


def map_model_for_fallback(model_name: str, fallback_model_override: str = "") -> str:
    """
    Map requested model name to upstream key-compatible Gemini model name.
    If the requested model is Claude, gracefully map it to Gemini 2.5 Pro
    so long-running runs don't break midway.
    """
    if fallback_model_override:
        return fallback_model_override

    cleaned = (model_name or "").strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[7:]

    # Remove anti-truncation prefixes if present
    for prefix in ("anti-truncate-", "notrunc-"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    lowered = cleaned.lower()

    # Model family mappings for Gemini API
    if "argon" in lowered:
        return "gemini-2.5-flash"
    elif "claude" in lowered:
        log.warning(
            f"[FALLBACK] Model '{model_name}' mapped to 'gemini-2.5-pro' for key-based Gemini fallback"
        )
        return "gemini-2.5-pro"
    elif "gemini-3.8-flash" in lowered:
        return "gemini-2.5-flash"

    return cleaned or "gemini-2.5-flash"


def _clean_gemini_payload_for_api(inner: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize Gemini format request payload for Google Generative Language API.
    Strips internal Antigravity CLI fields if present.
    """
    clean_dict = dict(inner)
    # Remove internal fields not recognized by standard Gemini API
    clean_dict.pop("sessionId", None)
    clean_dict.pop("labels", None)
    clean_dict.pop("model", None)
    clean_dict.pop("project", None)
    clean_dict.pop("requestId", None)
    clean_dict.pop("requestType", None)

    return clean_dict


async def fallback_stream_request(
    body: Dict[str, Any],
    native: bool = False,
    headers: Optional[Dict[str, str]] = None,
    log_ctx: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Union[bytes, str, Response], None]:
    """
    Execute streaming request via key-based fallback endpoint.
    """
    ctx = log_ctx or {}
    model_name = body.get("model", "")
    base_url = await get_fallback_base_url()
    override_model = await get_fallback_model()
    upstream_model = map_model_for_fallback(model_name, override_model)

    keys = await get_fallback_api_keys()
    if not keys:
        log.error("[FALLBACK] No fallback API keys configured")
        yield Response(
            content=json.dumps({"error": "Fallback requested but no fallback API keys available"}),
            status_code=500,
            media_type="application/json",
        )
        return

    inner = body.get("request", body)
    clean_payload = _clean_gemini_payload_for_api(inner)

    request_headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    if headers:
        for k, v in headers.items():
            if k.lower() not in ("authorization", "host", "content-length"):
                request_headers[k] = v

    log_start_time = time.time()
    usage_tokens: Dict[str, int] = {}
    last_error_chunk = None

    # Try configured fallback keys with round-robin / failover
    for key_attempt in range(min(len(keys), 3)):
        api_key = await get_next_fallback_key()
        target_url = f"{base_url}/models/{upstream_model}:streamGenerateContent?alt=sse&key={api_key}"
        masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"

        log.info(
            f"[FALLBACK STREAM] Routing to key-based API (model={upstream_model}, key={masked_key})"
        )

        success_received = False
        retry_next_key = False

        try:
            async for chunk in stream_post_async(
                url=target_url,
                body=clean_payload,
                native=native,
                headers=request_headers,
            ):
                if isinstance(chunk, Response):
                    status_code = chunk.status_code
                    last_error_chunk = chunk
                    log.warning(
                        f"[FALLBACK STREAM] Upstream key API returned error status {status_code}"
                    )
                    if status_code in (429, 503) and key_attempt < len(keys) - 1:
                        retry_next_key = True
                        break
                    yield chunk
                    return
                else:
                    success_received = True
                    if native is False and (b"usageMetadata" in chunk if isinstance(chunk, bytes) else "usageMetadata" in chunk):
                        extracted = extract_usage_tokens(chunk)
                        if extracted:
                            usage_tokens = extracted
                    yield chunk

            if retry_next_key:
                log.info("[FALLBACK STREAM] Rate limit on fallback key, trying next key...")
                continue

            if success_received:
                log.info(f"[FALLBACK STREAM] Key-based request completed successfully (model={upstream_model})")
                await record_usage_log({
                    "request_id": ctx.get("request_id") or new_request_id(),
                    "api_format": ctx.get("api_format", ""),
                    "client_ip": ctx.get("client_ip", ""),
                    "model_name": ctx.get("client_model") or model_name,
                    "upstream_model_name": f"[KEY:{upstream_model}]",
                    "credential_email": f"[KEY_FALLBACK:{masked_key}]",
                    "is_stream": True,
                    "status_code": 200,
                    "success": True,
                    "use_time": time.time() - log_start_time,
                    **usage_tokens,
                })
                return

        except Exception as e:
            log.error(f"[FALLBACK STREAM] Error during key stream request: {e}")
            if key_attempt < len(keys) - 1:
                log.info("[FALLBACK STREAM] Retrying with next fallback key...")
                continue
            else:
                yield Response(
                    content=json.dumps({"error": f"Fallback API request failed: {e}"}),
                    status_code=500,
                    media_type="application/json",
                )
                return

    if last_error_chunk:
        yield last_error_chunk
    else:
        yield Response(
            content=json.dumps({"error": "All fallback keys exhausted"}),
            status_code=500,
            media_type="application/json",
        )


async def fallback_non_stream_request(
    body: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    log_ctx: Optional[Dict[str, Any]] = None,
) -> Response:
    """
    Execute non-streaming request via key-based fallback endpoint.
    """
    ctx = log_ctx or {}
    model_name = body.get("model", "")
    base_url = await get_fallback_base_url()
    override_model = await get_fallback_model()
    upstream_model = map_model_for_fallback(model_name, override_model)

    keys = await get_fallback_api_keys()
    if not keys:
        log.error("[FALLBACK] No fallback API keys configured")
        return Response(
            content=json.dumps({"error": "Fallback requested but no fallback API keys available"}),
            status_code=500,
            media_type="application/json",
        )

    inner = body.get("request", body)
    clean_payload = _clean_gemini_payload_for_api(inner)

    request_headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    if headers:
        for k, v in headers.items():
            if k.lower() not in ("authorization", "host", "content-length"):
                request_headers[k] = v

    log_start_time = time.time()

    for key_attempt in range(min(len(keys), 3)):
        api_key = await get_next_fallback_key()
        target_url = f"{base_url}/models/{upstream_model}:generateContent?key={api_key}"
        masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"

        log.info(
            f"[FALLBACK] Routing to key-based API (model={upstream_model}, key={masked_key})"
        )

        try:
            response = await post_async(
                url=target_url,
                json=clean_payload,
                headers=request_headers,
            )

            if response.status_code == 200:
                log.info(f"[FALLBACK] Key-based request successful (model={upstream_model})")
                tokens = extract_usage_tokens(response.content)
                await record_usage_log({
                    "request_id": ctx.get("request_id") or new_request_id(),
                    "api_format": ctx.get("api_format", ""),
                    "client_ip": ctx.get("client_ip", ""),
                    "model_name": ctx.get("client_model") or model_name,
                    "upstream_model_name": f"[KEY:{upstream_model}]",
                    "credential_email": f"[KEY_FALLBACK:{masked_key}]",
                    "is_stream": False,
                    "status_code": 200,
                    "success": True,
                    "use_time": time.time() - log_start_time,
                    **tokens,
                })
                return Response(
                    content=response.content,
                    status_code=200,
                    headers=dict(response.headers),
                )
            elif response.status_code in (429, 503) and key_attempt < len(keys) - 1:
                log.warning(f"[FALLBACK] Key rate-limited (HTTP {response.status_code}), trying next key...")
                continue
            else:
                log.warning(f"[FALLBACK] Upstream key error {response.status_code}: {response.text[:300]}")
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )

        except Exception as e:
            log.error(f"[FALLBACK] Exception calling key-based API: {e}")
            if key_attempt < len(keys) - 1:
                continue
            return Response(
                content=json.dumps({"error": f"Fallback API exception: {e}"}),
                status_code=500,
                media_type="application/json",
            )

    return Response(
        content=json.dumps({"error": "All fallback keys exhausted"}),
        status_code=500,
        media_type="application/json",
    )
