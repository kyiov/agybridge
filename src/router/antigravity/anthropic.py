"""
Anthropic Router - Handles Anthropic/Claude format API requests via Antigravity
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from config import get_anti_truncation_max_attempts, get_api_password
from log import log

from src.utils import (
    get_base_model_from_feature_model,
    is_anti_truncation_model,
    authenticate_bearer,
)

from src.router.hi_check import is_health_check_request, create_health_check_response
from src.router.stream_passthrough import (
    build_streaming_response_or_error,
    prepend_async_item,
    read_first_async_item,
)

from src.models import ClaudeRequest, model_to_dict
from src.token_estimator import estimate_input_tokens
from src.api.antigravity import non_stream_request, stream_request
from src.converter.anthropic2gemini import (
    anthropic_to_gemini_request,
    gemini_to_anthropic_response,
    gemini_stream_to_anthropic_stream,
)
from src.converter.antigravity_fix import normalize_antigravity_request
from src.converter.anti_truncation import (
    AntiTruncationStreamProcessor,
    apply_anti_truncation,
)

router = APIRouter()


@router.post("/v1/messages")
async def messages(
    claude_request: ClaudeRequest,
    request: Request,
    _token: str = Depends(authenticate_bearer)
):
    """
    Handle Anthropic/Claude format messages requests (streaming and non-streaming).
    """
    log.debug(f"[ANTIGRAVITY-ANTHROPIC] Request for model: {claude_request.model}")

    normalized_dict = model_to_dict(claude_request)

    if is_health_check_request(normalized_dict, format="anthropic"):
        response = create_health_check_response(format="anthropic")
        return JSONResponse(content=response)

    use_anti_truncation = is_anti_truncation_model(claude_request.model)
    real_model = get_base_model_from_feature_model(claude_request.model)
    is_streaming = claude_request.stream

    if use_anti_truncation and not is_streaming:
        log.warning("Anti-truncation is only effective during streaming, ignoring for non-streaming request")

    normalized_dict["model"] = real_model
    gemini_dict = await anthropic_to_gemini_request(normalized_dict)
    gemini_dict["model"] = real_model
    gemini_dict = await normalize_antigravity_request(gemini_dict)

    api_request = {
        "model": gemini_dict.pop("model"),
        "request": gemini_dict
    }

    log_ctx = {
        "api_format": "anthropic",
        "client_ip": request.client.host if request.client else "",
        "client_model": claude_request.model,
    }

    # Non-streaming request
    if not is_streaming:
        response = await non_stream_request(body=api_request, log_ctx=log_ctx)
        status_code = getattr(response, "status_code", 200)

        if hasattr(response, "body"):
            response_body = response.body.decode() if isinstance(response.body, bytes) else response.body
        elif hasattr(response, "content"):
            response_body = response.content.decode() if isinstance(response.content, bytes) else response.content
        else:
            response_body = str(response)

        try:
            gemini_response = json.loads(response_body)
        except Exception as e:
            log.error(f"Failed to parse Gemini response: {e}")
            raise HTTPException(status_code=500, detail="Response parsing failed")

        anthropic_response = gemini_to_anthropic_response(
            gemini_response,
            real_model,
            status_code
        )

        return JSONResponse(content=anthropic_response, status_code=status_code)

    # Streaming with anti-truncation generator
    async def anti_truncation_generator():
        max_attempts = await get_anti_truncation_max_attempts()
        anti_truncation_payload = apply_anti_truncation(api_request)

        first_attempt_stream = stream_request(body=anti_truncation_payload, native=False, log_ctx=log_ctx)
        try:
            first_chunk = await read_first_async_item(first_attempt_stream)
        except StopAsyncIteration:
            return

        if isinstance(first_chunk, Response):
            yield first_chunk
            return

        first_attempt_pending = True

        async def stream_request_wrapper(payload):
            nonlocal first_attempt_pending

            if first_attempt_pending:
                first_attempt_pending = False
                stream_gen = prepend_async_item(first_chunk, first_attempt_stream)
            else:
                stream_gen = stream_request(body=payload, native=False, log_ctx=log_ctx)
            return StreamingResponse(stream_gen, media_type="text/event-stream")

        processor = AntiTruncationStreamProcessor(
            stream_request_wrapper,
            anti_truncation_payload,
            max_attempts,
        )

        async def bytes_wrapper():
            async for chunk in processor.process_stream():
                if isinstance(chunk, str):
                    yield chunk.encode('utf-8')
                else:
                    yield chunk

        async for anthropic_chunk in gemini_stream_to_anthropic_stream(
            bytes_wrapper(),
            real_model,
            200
        ):
            if anthropic_chunk:
                yield anthropic_chunk

    # Normal streaming generator
    async def normal_stream_generator():
        stream_gen = stream_request(body=api_request, native=False, log_ctx=log_ctx)
        try:
            first_chunk = await read_first_async_item(stream_gen)
        except StopAsyncIteration:
            return

        if isinstance(first_chunk, Response):
            yield first_chunk
            return

        async def gemini_chunk_wrapper():
            async for chunk in prepend_async_item(first_chunk, stream_gen):
                if isinstance(chunk, Response):
                    try:
                        error_content = chunk.body if isinstance(chunk.body, bytes) else (chunk.body or b'').encode('utf-8')
                        gemini_error = json.loads(error_content.decode('utf-8'))
                        anthropic_error = gemini_to_anthropic_response(
                            gemini_error,
                            real_model,
                            chunk.status_code
                        )
                        yield f"data: {json.dumps(anthropic_error)}\n\n".encode('utf-8')
                    except Exception:
                        yield f"data: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': 'Stream error'}})}\n\n".encode('utf-8')
                    yield b"data: [DONE]\n\n"
                    return
                else:
                    if isinstance(chunk, str):
                        yield chunk.encode('utf-8')
                    else:
                        yield chunk

        async for anthropic_chunk in gemini_stream_to_anthropic_stream(
            gemini_chunk_wrapper(),
            real_model,
            200
        ):
            if anthropic_chunk:
                yield anthropic_chunk

    if use_anti_truncation:
        log.info("Enabling streaming anti-truncation")
        return await build_streaming_response_or_error(anti_truncation_generator())
    else:
        return await build_streaming_response_or_error(normal_stream_generator())


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    _token: str = Depends(authenticate_bearer)
):
    """
    Handle Anthropic token count estimation request.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"type": "error", "error": {"type": "invalid_request_error", "message": f"Invalid JSON payload: {str(e)}"}}
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"type": "error", "error": {"type": "invalid_request_error", "message": "Request body must be a JSON object"}}
        )

    if not payload.get("model") or not isinstance(payload.get("messages"), list):
        return JSONResponse(
            status_code=400,
            content={"type": "error", "error": {"type": "invalid_request_error", "message": "Missing required fields: model / messages"}}
        )

    try:
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else "unknown"
    except Exception:
        client_host = "unknown"
        client_port = "unknown"

    thinking_present = "thinking" in payload
    thinking_value = payload.get("thinking")
    thinking_summary = None
    if thinking_present:
        if isinstance(thinking_value, dict):
            thinking_summary = {
                "type": thinking_value.get("type"),
                "budget_tokens": thinking_value.get("budget_tokens"),
            }
        else:
            thinking_summary = {"raw": str(thinking_value)}

    log_payload = {
        "model": payload.get("model"),
        "messages_count": len(payload.get("messages", [])),
        "has_system": "system" in payload,
        "tools_count": len(payload.get("tools", [])) if "tools" in payload else 0,
        "thinking": thinking_summary,
    }

    log.debug(
        f"[ANTIGRAVITY-ANTHROPIC] /messages/count_tokens request from client={client_host}:{client_port} payload={log_payload}"
    )

    try:
        input_tokens = estimate_input_tokens(payload)
        return JSONResponse(content={"input_tokens": input_tokens})
    except Exception as e:
        log.error(f"[ANTIGRAVITY-ANTHROPIC] Token estimation error: {e}")
        return JSONResponse(
            status_code=500,
            content={"type": "error", "error": {"type": "api_error", "message": f"Token estimation failed: {str(e)}"}}
        )
