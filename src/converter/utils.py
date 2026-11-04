from typing import Any, Dict

from src.converter.thoughtSignature_fix import (
    is_internal_placeholder_text,
    is_skip_thought_signature_placeholder,
)


def extract_content_and_reasoning(parts: list) -> tuple:
    """Extract regular content, reasoning content, and images from Gemini response parts.

    Args:
        parts: List of parts in Gemini response

    Returns:
        (content, reasoning_content, images): Tuple of text, reasoning, and image dictionaries
    """
    content = ""
    reasoning_content = ""
    images = []

    for part in parts:
        if is_skip_thought_signature_placeholder(part):
            continue

        text = part.get("text", "")
        if is_internal_placeholder_text(text):
            continue
        if text:
            if part.get("thought", False):
                reasoning_content += text
            else:
                content += text

        if "inlineData" in part:
            inline_data = part["inlineData"]
            mime_type = inline_data.get("mimeType", "image/png")
            base64_data = inline_data.get("data", "")
            images.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_data}"
                }
            })

    return content, reasoning_content, images


async def merge_system_messages(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process system messages in the request body:
    - Top-level system param (Anthropic format) merged with leading system messages into systemInstruction
    - Intermediate system messages converted into user messages preserving sequence

    Args:
        request_body: Request body dictionary

    Returns:
        Updated request body
    """
    system_content = request_body.get("system")
    if system_content:
        system_parts = []

        if isinstance(system_content, str):
            if system_content.strip():
                system_parts.append({"text": system_content})
        elif isinstance(system_content, list):
            for item in system_content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text", "").strip():
                        system_parts.append({"text": item["text"]})
                elif isinstance(item, str) and item.strip():
                    system_parts.append({"text": item})

        if system_parts:
            request_body = request_body.copy()
            request_body.pop("system", None)
            request_body["systemInstruction"] = {"parts": system_parts}

    messages = request_body.get("messages", [])
    if not messages:
        return request_body

    system_parts = []

    if "systemInstruction" in request_body:
        existing_instruction = request_body.get("systemInstruction", {})
        if isinstance(existing_instruction, dict):
            system_parts = existing_instruction.get("parts", []).copy()

    remaining_messages = []
    collecting_system = True
    instruction_roles = ("system", "developer")

    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")

        if role in instruction_roles and collecting_system:
            if isinstance(content, str):
                if content.strip():
                    system_parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and item.get("text", "").strip():
                            system_parts.append({"text": item["text"]})
                    elif isinstance(item, str) and item.strip():
                        system_parts.append({"text": item})
        else:
            collecting_system = False
            if role in instruction_roles:
                converted_message = message.copy()
                converted_message["role"] = "user"
                remaining_messages.append(converted_message)
            else:
                remaining_messages.append(message)

    if not system_parts:
        if remaining_messages == messages:
            return request_body
        result = request_body.copy()
        result["messages"] = remaining_messages
        return result

    result = request_body.copy()
    result["systemInstruction"] = {"parts": system_parts}
    result["messages"] = remaining_messages

    return result
