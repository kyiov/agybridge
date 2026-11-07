"""
OpenAI Router - Handles OpenAI format API requests via Antigravity
"""

import json
import sys
import uuid
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from config import get_anti_truncation_max_attempts
from log import log

from src.utils import (
    get_base_model_from_feature_model,
    resolve_upstream_model,
    is_anti_truncation_model,
    authenticate_bearer,
)

from src.router.hi_check import is_health_check_request, create_health_check_response
from src.router.stream_passthrough import (
    build_streaming_response_or_error,
    prepend_async_item,
    read_first_async_item,
)

from src.models import OpenAIChatCompletionRequest, model_to_dict
from src.api.antigravity import non_stream_request, stream_request
from src.converter.openai2gemini import (
    convert_openai_to_gemini_request,
    convert_gemini_to_openai_response,
    convert_gemini_to_openai_stream,
)
from src.converter.antigravity_fix import normalize_antigravity_request
from src.converter.anti_truncation import (
    AntiTruncationStreamProcessor,
    apply_anti_truncation,
)

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    openai_request: OpenAIChatCompletionRequest,
    request: Request,
    token: str = Depends(authenticate_bearer)
):
    """
    Handle OpenAI format chat completion requests (streaming and non-streaming).
    """
    log.debug(f"[ANTIGRAVITY-OPENAI] Request for model: {openai_request.model}")

    normalized_dict = model_to_dict(openai_request)

    if is_health_check_request(normalized_dict, format="openai"):
        response = create_health_check_response(format="openai")
        return JSONResponse(content=response)

    use_anti_truncation = is_anti_truncation_model(openai_request.model)
    real_model = resolve_upstream_model(openai_request.model)
    is_streaming = openai_request.stream

    if use_anti_truncation and not is_streaming:
        log.warning("Anti-truncation is only effective during streaming, ignoring for non-streaming request")

    normalized_dict["model"] = real_model

    try:
        gemini_dict = await convert_openai_to_gemini_request(normalized_dict)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    gemini_dict["model"] = real_model
    gemini_dict = await normalize_antigravity_request(gemini_dict)

    for content in gemini_dict.get("contents", []):
        if not isinstance(content, dict) or content.get("role") not in ("user", "model"):
            raise HTTPException(
                status_code=400, detail="Unrepresentable content role for Antigravity"
            )

    api_request = {
        "model": gemini_dict.pop("model"),
        "request": gemini_dict
    }

    log_ctx = {
        "api_format": "openai",
        "client_ip": request.client.host if request.client else "",
        "client_model": openai_request.model,
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

        openai_response = convert_gemini_to_openai_response(
            gemini_response,
            openai_request.model,
            status_code
        )

        return JSONResponse(content=openai_response, status_code=status_code)

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

        response_id = f"chatcmpl-{uuid.uuid4()}"

        async for chunk in processor.process_stream():
            if not chunk:
                continue

            lines = chunk.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line == "data: [DONE]":
                    yield "data: [DONE]\n\n"
                    return

                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        gemini_chunk = json.loads(data_str)
                        openai_chunks = convert_gemini_to_openai_stream(
                            gemini_chunk,
                            openai_request.model,
                            response_id
                        )

                        for openai_chunk in openai_chunks:
                            yield f"data: {json.dumps(openai_chunk)}\n\n"
                    except json.JSONDecodeError:
                        continue

        yield "data: [DONE]\n\n"

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

        response_id = f"chatcmpl-{uuid.uuid4()}"

        async for chunk in prepend_async_item(first_chunk, stream_gen):
            if isinstance(chunk, Response):
                try:
                    error_content = chunk.body if isinstance(chunk.body, bytes) else (chunk.body or b'').encode('utf-8')
                    gemini_error = json.loads(error_content.decode('utf-8'))
                    openai_error = convert_gemini_to_openai_response(
                        gemini_error,
                        real_model,
                        chunk.status_code
                    )
                    yield f"data: {json.dumps(openai_error)}\n\n"
                except Exception:
                    yield f"data: {json.dumps({'error': {'message': 'Stream error', 'type': 'internal_error', 'code': chunk.status_code}})}\n\n"
                yield "data: [DONE]\n\n"
                return

            if isinstance(chunk, bytes):
                chunk = chunk.decode('utf-8')

            lines = chunk.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line == "data: [DONE]":
                    yield "data: [DONE]\n\n"
                    return

                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        gemini_chunk = json.loads(data_str)
                        openai_chunks = convert_gemini_to_openai_stream(
                            gemini_chunk,
                            openai_request.model,
                            response_id
                        )

                        for openai_chunk in openai_chunks:
                            yield f"data: {json.dumps(openai_chunk)}\n\n"
                    except json.JSONDecodeError:
                        continue

        yield "data: [DONE]\n\n"

    if use_anti_truncation:
        log.info("Enabling streaming anti-truncation")
        return await build_streaming_response_or_error(anti_truncation_generator())
    else:
        return await build_streaming_response_or_error(normal_stream_generator())
