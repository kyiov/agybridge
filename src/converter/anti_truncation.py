"""
Anti-Truncation Module - Synthetic Tool Call Approach
Directs the model to output final answers into the 'content' parameter of a synthetic
functionCall (emit_answer), allowing the gateway to reconstruct regular assistant text
and bypass external truncation limitations.

Enforcement: toolConfig.functionCallingConfig.mode=ANY + allowedFunctionNames
Structurally enforces calling one of the allowed tools (including emit_answer).
If upstream ignores toolConfig, the streaming processor falls back cleanly.
"""

import io
import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import Response as FastAPIResponse
from fastapi.responses import StreamingResponse

from src.converter.thoughtSignature_fix import SKIP_THOUGHT_SIGNATURE_VALIDATOR

# ==================== Synthetic Tool Configuration ====================

SYNTHETIC_TOOL_NAME = "emit_answer"

# Finish reasons indicating truncation (triggers continuation when hit by synthetic tool)
# STOP / SAFETY are treated as natural completion without continuation
TRUNCATION_FINISH_REASONS = {"MAX_TOKENS"}

SYNTHETIC_TOOL_DECLARATION = {
    "name": SYNTHETIC_TOOL_NAME,
    "description": (
        "You MUST call this tool exactly once to output your final user-visible answer. "
        "Put the complete answer in the 'content' argument. "
        "Do NOT output any text outside this tool call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The complete final answer to output to the user.",
            },
        },
        "required": ["content"],
    },
}

CONTROL_INSTRUCTION = f"""Answer output rules (processed by gateway, please structure your output accordingly):

1. Your final response MUST be output by calling the `{SYNTHETIC_TOOL_NAME}` tool, placing your entire answer in the `content` parameter.
2. The `content` parameter contains the complete natural language answer for the user (can include Markdown, code blocks, etc.).
3. Do NOT output any plain text outside the tool call.
4. For lengthy answers, you may output in segments across multiple `{SYNTHETIC_TOOL_NAME}` calls. Do not shorten or omit content.

If your response is truncated, the system will prompt you to continue, which you should do via `{SYNTHETIC_TOOL_NAME}`."""

CONTINUATION_PROMPT = f"""Your previous response was truncated. Please call the `{SYNTHETIC_TOOL_NAME}` tool to continue outputting all remaining content.

Important reminders:
1. Do not repeat what was already output.
2. Continue directly without preface or explanations.
3. Place remaining content in the `content` parameter of `{SYNTHETIC_TOOL_NAME}`.

Now continue output:"""


# ==================== Request Injection ====================


def _collect_function_tool_names(tools: List[Dict[str, Any]]) -> List[str]:
    """Collect tool names from all functionDeclarations in tools."""
    names: List[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        for decl in tool.get("functionDeclarations") or []:
            if isinstance(decl, dict) and decl.get("name"):
                names.append(decl["name"])
    return names


def _has_non_function_tool(tools: List[Dict[str, Any]]) -> bool:
    """Determine whether tools contain non-function built-ins (e.g. googleSearch, codeExecution)."""
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("functionDeclarations"):
            continue
        return True
    return False


def _resolve_function_calling_mode(tools: List[Dict[str, Any]]) -> Tuple[str, bool]:
    """Determine injected functionCallingConfig mode."""
    if not _has_non_function_tool(tools):
        return "ANY", True
    return "AUTO", False


def apply_anti_truncation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply anti-truncation to request payload: inject synthetic tool and control instructions.

    Args:
        payload: Original request payload, formatted as {"model": ..., "request": {...}}

    Returns:
        Payload with injected synthetic tool and control instructions.
    """
    modified_payload = payload.copy()
    request_data = dict(modified_payload.get("request") or {})

    # 1. Inject synthetic tool into tools list
    tools = list(request_data.get("tools") or [])
    already_injected = any(
        isinstance(tool, dict)
        and any(
            decl.get("name") == SYNTHETIC_TOOL_NAME
            for decl in (tool.get("functionDeclarations") or [])
            if isinstance(decl, dict)
        )
        for tool in tools
    )
    if not already_injected:
        tools.append({"functionDeclarations": [SYNTHETIC_TOOL_DECLARATION]})
        request_data["tools"] = tools

    # 2. Inject toolConfig.functionCallingConfig
    tool_config = json.loads(
        json.dumps(request_data.get("toolConfig") or {}, ensure_ascii=False)
    )
    func_config = dict(tool_config.get("functionCallingConfig") or {})
    mode, use_allowed = _resolve_function_calling_mode(tools)
    func_config["mode"] = mode
    if use_allowed:
        existing_allowed = [
            n for n in (func_config.get("allowedFunctionNames") or []) if isinstance(n, str)
        ]
        allowed_names = _collect_function_tool_names(tools)
        merged = existing_allowed + [n for n in allowed_names if n not in existing_allowed]
        seen = set()
        merged = [n for n in merged if not (n in seen or seen.add(n))]
        func_config["allowedFunctionNames"] = merged
        tool_config["functionCallingConfig"] = func_config
        request_data["toolConfig"] = tool_config
        print(
            f"Anti-truncation: toolConfig mode=ANY allowedFunctionNames={merged}",
            flush=True,
        )
    else:
        tool_config["functionCallingConfig"] = func_config
        request_data["toolConfig"] = tool_config
        print(
            "Anti-truncation: toolConfig mode=AUTO (non-function tools present), "
            "relying on instruction only",
            flush=True,
        )

    # 3. Inject control instruction to systemInstruction
    system_instruction = dict(request_data.get("systemInstruction") or {})
    if "parts" not in system_instruction:
        system_instruction["parts"] = []
    else:
        system_instruction["parts"] = list(system_instruction["parts"])

    has_control_instruction = any(
        isinstance(part, dict) and SYNTHETIC_TOOL_NAME in part.get("text", "")
        for part in system_instruction["parts"]
    )
    if not has_control_instruction:
        system_instruction["parts"].append({"text": CONTROL_INSTRUCTION})
        request_data["systemInstruction"] = system_instruction

    modified_payload["request"] = request_data
    return modified_payload


# ==================== Response Extraction ====================


def extract_synthetic_content_from_response(
    data: Dict[str, Any],
) -> Tuple[str, bool]:
    """
    Extract synthetic tool content from Gemini response.

    Args:
        data: Gemini response data (may contain response wrapper)

    Returns:
        (synthetic_content, found_synthetic) tuple:
        - synthetic_content: Extracted text from emit_answer tool
        - found_synthetic: Whether synthetic tool call was present
    """
    if "response" in data:
        data = data["response"]

    synthetic_content = ""
    found_synthetic = False

    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if not isinstance(part, dict):
                continue
            if "functionCall" in part:
                fc = part["functionCall"]
                if fc.get("name") == SYNTHETIC_TOOL_NAME:
                    found_synthetic = True
                    args = fc.get("args", {})
                    if isinstance(args, dict):
                        synthetic_content += args.get("content", "")
                    elif isinstance(args, str):
                        extracted = _extract_content_from_json_str(args)
                        if extracted is not None:
                            synthetic_content += extracted

    return synthetic_content, found_synthetic


def _extract_content_from_json_str(args_str: str) -> Optional[str]:
    """Extract content field from JSON string with regex fallback."""
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict) and "content" in parsed:
            return str(parsed["content"])
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(
        r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"',
        args_str,
        re.DOTALL,
    )
    if match:
        raw_content = match.group(1)
        try:
            return json.loads(f'"{raw_content}"')
        except (json.JSONDecodeError, ValueError):
            return (
                raw_content.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )

    return None


def _chunk_has_real_function_call(data: Dict[str, Any]) -> bool:
    """Determine whether chunk carries a real function call (not emit_answer)."""
    if "response" in data:
        data = data["response"]
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if (
                isinstance(part, dict)
                and "functionCall" in part
                and part["functionCall"].get("name") != SYNTHETIC_TOOL_NAME
            ):
                return True
    return False


def _replace_thought_signatures(data: Dict[str, Any]) -> bool:
    """
    Replace real thoughtSignature with skip validator placeholder before returning to client.
    """
    if not isinstance(data, dict):
        return False
    inner = data.get("response") if "response" in data else data
    if not isinstance(inner, dict):
        return False

    replaced = False
    for candidate in inner.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            signature = part.get("thoughtSignature")
            if signature and signature != SKIP_THOUGHT_SIGNATURE_VALIDATOR:
                part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE_VALIDATOR
                replaced = True
    return replaced


def build_text_chunk_from_synthetic(
    original_data: Dict[str, Any],
    synthetic_content: str,
) -> Dict[str, Any]:
    """
    Build regular text chunk from synthetic tool content.

    Args:
        original_data: Original Gemini chunk data
        synthetic_content: Text extracted from synthetic tool

    Returns:
        Modified chunk data with functionCall replaced by text part.
    """
    has_response_wrapper = "response" in original_data
    if has_response_wrapper:
        inner_data = original_data["response"]
    else:
        inner_data = original_data

    modified_inner = inner_data.copy()
    modified_candidates = []

    for candidate in inner_data.get("candidates", []):
        modified_candidate = candidate.copy()
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        new_parts = []
        for part in parts:
            if not isinstance(part, dict):
                new_parts.append(part)
                continue

            if "functionCall" in part:
                fc = part["functionCall"]
                if fc.get("name") == SYNTHETIC_TOOL_NAME:
                    if synthetic_content:
                        new_parts.append({"text": synthetic_content})
                    continue
                else:
                    new_parts.append(part)
            else:
                new_parts.append(part)

        modified_content = content.copy()
        modified_content["parts"] = new_parts
        modified_candidate["content"] = modified_content
        modified_candidates.append(modified_candidate)

    modified_inner["candidates"] = modified_candidates

    if has_response_wrapper:
        result = original_data.copy()
        result["response"] = modified_inner
        return result
    return modified_inner


# ==================== Stream Processor ====================


def _deep_copy_anti_truncation_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Perform JSON-based deep copy of request payload."""
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False))
    except (TypeError, ValueError):
        return payload.copy()


class AntiTruncationStreamProcessor:
    """
    Anti-truncation streaming processor using synthetic tool call technique.
    Passes text chunks in real-time when plain text is received, falling back
    cleanly and handling continuation upon truncation.
    """

    def __init__(
        self,
        original_request_func,
        payload: Dict[str, Any],
        max_attempts: int = 3,
    ):
        self.original_request_func = original_request_func
        self.base_payload = _deep_copy_anti_truncation_payload(payload)
        self.max_attempts = max_attempts
        self.collected_content = io.StringIO()
        self.current_attempt = 0
        self.forwarded_any_text = False

    def _get_collected_text(self) -> str:
        """Get accumulated text content"""
        return self.collected_content.getvalue()

    def _append_content(self, content: str):
        """Append content to accumulator"""
        if content:
            self.collected_content.write(content)

    def _clear_content(self):
        """Clear accumulated content and release memory"""
        self.collected_content.close()
        self.collected_content = io.StringIO()

    async def process_stream(self) -> AsyncGenerator[bytes, None]:
        """Process streaming response, detecting and handling truncation."""

        while self.current_attempt < self.max_attempts:
            self.current_attempt += 1

            current_payload = self._build_current_payload()

            found_synthetic = False
            side_buffer = io.StringIO()
            last_finish_reason: Optional[str] = None
            finish_reason_forwarded = False

            try:
                response = await self.original_request_func(current_payload)

                if not isinstance(response, StreamingResponse):
                    raw = await self._handle_non_streaming_response(response)
                    if isinstance(raw, bytes):
                        yield f"data: {raw.decode('utf-8', errors='ignore').strip()}\n\n".encode("utf-8")
                    else:
                        yield f"data: {str(raw).strip()}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return

                async for line in response.body_iterator:
                    if not line:
                        yield line
                        continue

                    if isinstance(line, FastAPIResponse):
                        print(
                            f"Anti-truncation: Received Response object from stream "
                            f"(status={line.status_code}), treating as error",
                            flush=True,
                        )
                        error_chunk = {
                            "error": {
                                "message": (
                                    line.body.decode("utf-8", errors="ignore")
                                    if hasattr(line, "body") and line.body
                                    else "Upstream error"
                                ),
                                "type": "api_error",
                                "code": line.status_code,
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return

                    if isinstance(line, bytes):
                        line_str = line.decode("utf-8", errors="ignore").strip()
                    else:
                        line_str = str(line).strip()

                    if not line_str:
                        yield line
                        continue

                    if line_str.startswith("data: "):
                        payload_str = line_str[6:]

                        if payload_str.strip() == "[DONE]":
                            if found_synthetic:
                                if (
                                    last_finish_reason in TRUNCATION_FINISH_REASONS
                                    and self.current_attempt < self.max_attempts
                                ):
                                    break
                                print(
                                    f"Anti-truncation: outcome=synthetic_hit "
                                    f"(attempt {self.current_attempt}, "
                                    f"content length: {len(self._get_collected_text())}, "
                                    f"finishReason: {last_finish_reason})",
                                    flush=True,
                                )
                                side_buffer.close()
                                self._clear_content()
                                if not finish_reason_forwarded:
                                    yield self._build_finish_reason_chunk()
                                yield line
                                return
                            else:
                                print(
                                    f"Anti-truncation: outcome=no_synthetic_eot "
                                    f"(attempt {self.current_attempt}, "
                                    f"forwarded text length: {len(side_buffer.getvalue())}), "
                                    "preparing continuation",
                                    flush=True,
                                )
                                break

                        try:
                            data = json.loads(payload_str)
                        except (json.JSONDecodeError, ValueError):
                            yield line
                            continue

                        if _replace_thought_signatures(data):
                            line = (
                                f"data: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n\n"
                            ).encode("utf-8")

                        synthetic_content, chunk_has_synthetic = (
                            extract_synthetic_content_from_response(data)
                        )

                        if chunk_has_synthetic:
                            found_synthetic = True
                            chunk_finish = self._get_finish_reason(data)
                            if chunk_finish:
                                last_finish_reason = chunk_finish

                            if side_buffer.getvalue():
                                print(
                                    "Anti-truncation: Model output plain text before "
                                    "synthetic tool call, synthetic content wins "
                                    "(forwarded text conflicts and is dropped)",
                                    flush=True,
                                )
                                side_buffer.close()
                                side_buffer = io.StringIO()

                            self._append_content(synthetic_content)

                            is_truncated = chunk_finish in TRUNCATION_FINISH_REASONS
                            if is_truncated:
                                stripped_data = self._strip_finish_reason(data)
                                modified_data = build_text_chunk_from_synthetic(
                                    stripped_data, synthetic_content
                                )
                            else:
                                modified_data = build_text_chunk_from_synthetic(
                                    data, synthetic_content
                                )
                            json_str = json.dumps(
                                modified_data, separators=(",", ":"), ensure_ascii=False
                            )
                            yield f"data: {json_str}\n\n".encode("utf-8")

                            if chunk_finish and not is_truncated:
                                last_finish_reason = chunk_finish
                                finish_reason_forwarded = True

                        elif _chunk_has_real_function_call(data):
                            chunk_finish = self._get_finish_reason(data)
                            if chunk_finish:
                                last_finish_reason = chunk_finish
                                finish_reason_forwarded = True
                            yield line

                        else:
                            if found_synthetic:
                                if self._has_finish_reason(data):
                                    last_finish_reason = self._get_finish_reason(data)
                                    finish_reason_forwarded = True
                                    stripped = self._strip_text_parts(data)
                                    json_str = json.dumps(
                                        stripped, separators=(",", ":"), ensure_ascii=False
                                    )
                                    yield f"data: {json_str}\n\n".encode("utf-8")
                                continue
                            else:
                                text = self._extract_text_from_chunk(data)
                                if text:
                                    side_buffer.write(text)
                                    self.forwarded_any_text = True
                                    if self._has_finish_reason(data):
                                        stripped = self._strip_finish_reason(data)
                                        json_str = json.dumps(
                                            stripped, separators=(",", ":"), ensure_ascii=False
                                        )
                                        yield f"data: {json_str}\n\n".encode("utf-8")
                                    else:
                                        yield line
                                chunk_finish = self._get_finish_reason(data)
                                if chunk_finish:
                                    last_finish_reason = chunk_finish
                                    continue
                                if not text:
                                    yield line
                                continue

                    else:
                        yield line

                side_text = side_buffer.getvalue()
                side_buffer.close()

                if found_synthetic:
                    if last_finish_reason in TRUNCATION_FINISH_REASONS and self.current_attempt < self.max_attempts:
                        print(
                            f"Anti-truncation: outcome=synthetic_truncated "
                            f"(attempt {self.current_attempt} -> {self.current_attempt + 1}, "
                            f"content length: {len(self._get_collected_text())}, "
                            f"finishReason: {last_finish_reason})",
                            flush=True,
                        )
                        continue
                    content_len = len(self._get_collected_text())
                    self._clear_content()
                    print(
                        f"Anti-truncation: outcome=synthetic_hit "
                        f"(attempt {self.current_attempt}, stream ended without [DONE], "
                        f"content length: {content_len}, "
                        f"finishReason: {last_finish_reason})",
                        flush=True,
                    )
                    if not finish_reason_forwarded:
                        yield self._build_finish_reason_chunk()
                    yield b"data: [DONE]\n\n"
                    return

                if last_finish_reason == "STOP":
                    print(
                        f"Anti-truncation: outcome=stop_plain_text "
                        f"(attempt {self.current_attempt}, "
                        f"text length: {len(side_text)}, finishReason=STOP "
                        "without synthetic tool call), treating as complete",
                        flush=True)
                    if not finish_reason_forwarded:
                        yield self._build_finish_reason_chunk(last_finish_reason)
                    self._clear_content()
                    yield b"data: [DONE]\n\n"
                    return

                if side_text:
                    self._append_content(side_text)

                if self.current_attempt < self.max_attempts:
                    accumulated_text = self._get_collected_text()
                    print(
                        f"Anti-truncation: outcome=continuation "
                        f"(attempt {self.current_attempt} -> {self.current_attempt + 1}, "
                        f"accumulated length: {len(accumulated_text)}, "
                        f"last finishReason: {last_finish_reason})",
                        flush=True,
                    )
                    continue
                else:
                    print(
                        f"Anti-truncation: outcome=max_attempts_reached "
                        f"(attempt {self.current_attempt}, "
                        f"forwarded text length: {len(side_text)})",
                        flush=True,
                    )
                    if side_text and not finish_reason_forwarded:
                        yield self._build_finish_reason_chunk(last_finish_reason or "STOP")
                    self._clear_content()
                    yield b"data: [DONE]\n\n"
                    return

            except Exception as e:
                print(
                    f"Anti-truncation: outcome=error "
                    f"(attempt {self.current_attempt}): {str(e)}",
                    flush=True,
                )

                try:
                    interrupted_text = side_buffer.getvalue()
                except ValueError:
                    interrupted_text = ""
                try:
                    side_buffer.close()
                except ValueError:
                    pass
                if interrupted_text:
                    print(
                        f"Anti-truncation: Stream interrupted, salvaging "
                        f"{len(interrupted_text)} chars of buffered text into continuation history",
                        flush=True,
                    )
                    self._append_content(interrupted_text)

                if self.current_attempt >= self.max_attempts:
                    salvaged = self._get_collected_text()
                    self._clear_content()
                    if salvaged and self.forwarded_any_text:
                        print(
                            f"Anti-truncation: Max attempts reached after error, "
                            f"salvaged text already forwarded (length: {len(salvaged)})",
                            flush=True,
                        )
                        if not finish_reason_forwarded:
                            yield self._build_finish_reason_chunk(last_finish_reason or "STOP")
                    elif salvaged:
                        print(
                            f"Anti-truncation: Max attempts reached after error, "
                            f"yielding salvaged text (length: {len(salvaged)})",
                            flush=True,
                        )
                        fallback_chunk = self._build_fallback_text_chunk(salvaged)
                        if fallback_chunk:
                            yield fallback_chunk
                    else:
                        error_chunk = {
                            "error": {
                                "message": f"Anti-truncation failed: {str(e)}",
                                "type": "api_error",
                                "code": 500,
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n".encode()
                    yield b"data: [DONE]\n\n"
                    return
                continue

        print("Anti-truncation: outcome=all_attempts_failed", flush=True)
        self._clear_content()
        yield b"data: [DONE]\n\n"

    def _build_current_payload(self) -> Dict[str, Any]:
        """Build payload for current request attempt"""
        if self.current_attempt == 1:
            return self.base_payload

        continuation_payload = dict(self.base_payload)
        request_data = dict(continuation_payload.get("request") or {})
        new_contents = [
            dict(c) if isinstance(c, dict) else c
            for c in (request_data.get("contents") or [])
        ]

        accumulated_text = self._get_collected_text()
        if accumulated_text:
            new_contents.append({"role": "model", "parts": [{"text": accumulated_text}]})

        content_summary = ""
        if accumulated_text:
            if len(accumulated_text) > 200:
                content_summary = (
                    f"\n\nPreviously you already output about {len(accumulated_text)} characters, "
                    f'ending with:\n"...{accumulated_text[-100:]}"'
                )
            else:
                content_summary = f'\n\nPreviously you already output:\n"{accumulated_text}"'

        detailed_continuation_prompt = f"{CONTINUATION_PROMPT}{content_summary}"

        continuation_message = {"role": "user", "parts": [{"text": detailed_continuation_prompt}]}
        new_contents.append(continuation_message)

        request_data["contents"] = new_contents
        continuation_payload["request"] = request_data

        return continuation_payload

    def _extract_text_from_chunk(self, data: Dict[str, Any]) -> str:
        """Extract plain text from chunk data"""
        if "response" in data:
            data = data["response"]

        text = ""
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    text += part["text"]
        return text

    @staticmethod
    def _has_finish_reason(data: Dict[str, Any]) -> bool:
        """Determine whether chunk carries a finishReason."""
        if "response" in data:
            data = data["response"]
        for candidate in data.get("candidates", []):
            if candidate.get("finishReason"):
                return True
        return False

    @staticmethod
    def _get_finish_reason(data: Dict[str, Any]) -> Optional[str]:
        """Extract finishReason value from chunk if present."""
        if "response" in data:
            data = data["response"]
        for candidate in data.get("candidates", []):
            reason = candidate.get("finishReason")
            if reason:
                return reason
        return None

    @staticmethod
    def _strip_text_parts(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove text parts from chunk while keeping finishReason and other control fields."""
        has_wrapper = "response" in data
        inner = data["response"] if has_wrapper else data

        modified_inner = inner.copy()
        modified_candidates = []
        for candidate in inner.get("candidates", []):
            modified_candidate = candidate.copy()
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            new_parts = [
                part for part in parts
                if not (isinstance(part, dict) and "text" in part)
            ]
            modified_content = content.copy()
            modified_content["parts"] = new_parts
            modified_candidate["content"] = modified_content
            modified_candidates.append(modified_candidate)

        modified_inner["candidates"] = modified_candidates
        if has_wrapper:
            result = data.copy()
            result["response"] = modified_inner
            return result
        return modified_inner

    @staticmethod
    def _strip_finish_reason(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove finishReason from all candidates in chunk while keeping text."""
        has_wrapper = "response" in data
        inner = data["response"] if has_wrapper else data

        modified_inner = inner.copy()
        modified_candidates = []
        for candidate in inner.get("candidates", []):
            if not isinstance(candidate, dict) or "finishReason" not in candidate:
                modified_candidates.append(candidate)
                continue
            modified_candidate = candidate.copy()
            modified_candidate.pop("finishReason", None)
            modified_candidates.append(modified_candidate)

        modified_inner["candidates"] = modified_candidates
        if has_wrapper:
            result = data.copy()
            result["response"] = modified_inner
            return result
        return modified_inner

    def _build_fallback_text_chunk(self, text: str) -> Optional[bytes]:
        """Build fallback text chunk when no synthetic tool call occurred."""
        if not text:
            return None

        chunk = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": text}]},
                    "index": 0,
                }
            ]
        }
        json_str = json.dumps(chunk, separators=(",", ":"), ensure_ascii=False)
        return f"data: {json_str}\n\n".encode("utf-8")

    def _build_finish_reason_chunk(self, finish_reason: str = "STOP") -> bytes:
        """Build finishReason control chunk with text stripped."""
        chunk = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": []},
                    "finishReason": finish_reason,
                    "index": 0,
                }
            ]
        }
        json_str = json.dumps(chunk, separators=(",", ":"), ensure_ascii=False)
        return f"data: {json_str}\n\n".encode("utf-8")

    async def _handle_non_streaming_response(self, response) -> bytes:
        """Handle non-streaming response"""
        while True:
            try:
                if isinstance(response, StreamingResponse):
                    print(
                        "Anti-truncation: Received StreamingResponse in non-streaming handler",
                        flush=True,
                    )
                    chunks = []
                    async for chunk in response.body_iterator:
                        chunks.append(chunk)
                    content = b"".join(chunks).decode() if chunks else ""
                elif hasattr(response, "body"):
                    content = (
                        response.body.decode()
                        if isinstance(response.body, bytes)
                        else response.body
                    )
                elif hasattr(response, "content"):
                    content = (
                        response.content.decode()
                        if isinstance(response.content, bytes)
                        else response.content
                    )
                else:
                    print(f"Anti-truncation: Unknown response type: {type(response)}", flush=True)
                    content = str(response)

                if not content or not content.strip():
                    print("Anti-truncation: Received empty response content", flush=True)
                    return json.dumps(
                        {
                            "error": {
                                "message": "Empty response from server",
                                "type": "api_error",
                                "code": 500,
                            }
                        }
                    ).encode()

                try:
                    response_data = json.loads(content)
                except json.JSONDecodeError as json_err:
                    print(
                        f"Anti-truncation: Failed to parse JSON response: {json_err}, "
                        f"content: {content[:200]}",
                        flush=True,
                    )
                    return content.encode() if isinstance(content, str) else content

                if isinstance(response_data, dict) and "error" in response_data:
                    print(
                        f"Anti-truncation: Upstream error response "
                        f"(status={getattr(response, 'status_code', 'unknown')})",
                        flush=True,
                    )
                    return content.encode() if isinstance(content, str) else content

                synthetic_content, found_synthetic = (
                    extract_synthetic_content_from_response(response_data)
                )

                if found_synthetic or self.current_attempt >= self.max_attempts:
                    if found_synthetic:
                        modified_data = build_text_chunk_from_synthetic(
                            response_data, synthetic_content
                        )
                        _replace_thought_signatures(modified_data)
                        return json.dumps(modified_data, ensure_ascii=False).encode()
                    if isinstance(response_data, dict) and _replace_thought_signatures(
                        response_data
                    ):
                        return json.dumps(response_data, ensure_ascii=False).encode()
                    return content.encode() if isinstance(content, str) else content

                if synthetic_content:
                    self._append_content(synthetic_content)
                else:
                    text = self._extract_text_from_chunk(response_data)
                    if text:
                        self._append_content(text)

                print("Anti-truncation: Non-streaming response needs continuation", flush=True)
                self.current_attempt += 1
                next_payload = self._build_current_payload()
                response = await self.original_request_func(next_payload)

            except Exception as e:
                print(f"Anti-truncation non-streaming error: {str(e)}", flush=True)
                return json.dumps(
                    {
                        "error": {
                            "message": f"Anti-truncation failed: {str(e)}",
                            "type": "api_error",
                            "code": 500,
                        }
                    }
                ).encode()
