"""
OpenAI Transfer Module - Handles conversion between OpenAI and Gemini API formats
Called by openai-router, handles bidirectional conversion between OpenAI and Gemini formats
"""

import base64
import copy
import json
import re
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple, Union

from pypinyin import Style, lazy_pinyin

from src.converter.thoughtSignature_fix import (
    decode_tool_id_and_signature,
    is_internal_placeholder_text,
    is_skip_thought_signature_placeholder,
    SKIP_THOUGHT_SIGNATURE_VALIDATOR,
)
from src.converter.utils import merge_system_messages

from log import log

#: Tool call indices allocated per response_id in streaming responses.
#: Gemini's parallel functionCall uses 'one part per chunk'. If parts index within chunk
#: is used as OpenAI tool_calls[].index, each call receives 0. Under the OpenAI streaming spec,
#: clients merging chunks would place them in the same slot, concatenating arguments into invalid JSON
#: like {"a":1}{"b":2}. Sequential indices are assigned per stream instead.
_STREAM_TOOL_INDEX: "OrderedDict[str, int]" = OrderedDict()

#: Capacity limit: streams abandoned midway (client disconnects, missing finishReason block) are not reclaimed,
#: using LRU eviction as fallback to prevent unbounded growth in long-running instances.
_STREAM_TOOL_INDEX_MAX_ENTRIES = 512


def _next_stream_tool_call_indices(response_id: str, count: int) -> List[int]:
    """Allocate sequential stream indices for count tool calls within this chunk."""
    base = _STREAM_TOOL_INDEX.get(response_id, 0)
    _STREAM_TOOL_INDEX[response_id] = base + count
    _STREAM_TOOL_INDEX.move_to_end(response_id)
    while len(_STREAM_TOOL_INDEX) > _STREAM_TOOL_INDEX_MAX_ENTRIES:
        _STREAM_TOOL_INDEX.popitem(last=False)
    return list(range(base, base + count))

def _convert_usage_metadata(usage_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert Gemini usageMetadata to OpenAI format usage fields

    Semantic alignment (Gemini -> OpenAI):
    - Gemini promptTokenCount includes cached tokens -> OpenAI prompt_tokens also includes cached tokens
    - Gemini candidatesTokenCount excludes reasoning tokens -> OpenAI completion_tokens includes reasoning tokens
      (completion_tokens = candidatesTokenCount + thoughtsTokenCount)
    - Detailed fields: prompt_tokens_details.cached_tokens / completion_tokens_details.reasoning_tokens

    Args:
        usage_metadata: Gemini API usageMetadata dictionary

    Returns:
        OpenAI format usage dictionary, or None if no usage data
    """
    if not usage_metadata:
        return None

    prompt_tokens = int(usage_metadata.get("promptTokenCount", 0) or 0)
    cached_tokens = int(usage_metadata.get("cachedContentTokenCount", 0) or 0)
    reasoning_tokens = int(usage_metadata.get("thoughtsTokenCount", 0) or 0)
    completion_tokens = (
        int(usage_metadata.get("candidatesTokenCount", 0) or 0) + reasoning_tokens
    )
    total_tokens = int(
        usage_metadata.get(
            "totalTokenCount",
            prompt_tokens + completion_tokens,
        )
        or 0
    )

    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }

    if cached_tokens > 0:
        usage["prompt_tokens_details"] = {"cached_tokens": cached_tokens}

    if reasoning_tokens > 0:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}

    return usage


def _build_message_with_reasoning(role: str, content: str, reasoning_content: str) -> dict:
    """Build message object with optional reasoning content"""
    message = {"role": role, "content": content}

    # Add reasoning_content if thinking tokens exist
    if reasoning_content:
        message["reasoning_content"] = reasoning_content

    return message


def _map_finish_reason(gemini_reason: str) -> str:
    """
    Map Gemini finish reason to OpenAI finish reason

    Args:
        gemini_reason: Finish reason from Gemini API

    Returns:
        OpenAI-compatible finish reason
    """
    if gemini_reason == "STOP":
        return "stop"
    elif gemini_reason == "MAX_TOKENS":
        return "length"
    elif gemini_reason in ["SAFETY", "RECITATION"]:
        return "content_filter"
    else:
        # For None or unknown finishReason, return "stop" as default
        # Prevents returning None which causes MCP clients to mistake response as incomplete and loop
        return "stop"


# ==================== Tool Conversion Functions ====================


def _normalize_function_name(name: str) -> str:
    """
    Normalize function name to conform to Gemini API requirements

    Rules:
    - Must start with a letter or underscore
    - Can only contain a-z, A-Z, 0-9, underscore, dot, hyphen
    - Maximum length 64 characters

    Conversion strategy:
    1. Convert Chinese characters to pinyin
    2. Replace illegal characters with underscore
    3. Add underscore prefix if not starting with letter/underscore
    4. Truncate to 64 characters

    Args:
        name: Original function name

    Returns:
        Normalized function name
    """
    if not name:
        return "_unnamed_function"

    # Step 1: Convert Chinese characters to pinyin
    if re.search(r"[\u4e00-\u9fff]", name):
        try:
            parts = []
            for char in name:
                if "\u4e00" <= char <= "\u9fff":
                    # Convert Chinese characters to pinyin
                    pinyin = lazy_pinyin(char, style=Style.NORMAL)
                    parts.append("".join(pinyin))
                else:
                    parts.append(char)
            normalized = "".join(parts)
        except ImportError:
            log.warning("pypinyin not installed, cannot convert Chinese characters to pinyin")
            normalized = name
    else:
        normalized = name

    # Step 2: Replace invalid characters with underscore
    # Valid characters: a-z, A-Z, 0-9, _, ., -
    normalized = re.sub(r"[^a-zA-Z0-9_.\-]", "_", normalized)

    # Step 3: Ensure starts with letter or underscore
    if normalized and not (normalized[0].isalpha() or normalized[0] == "_"):
        # Add underscore prefix if starting with digit, dot, or hyphen
        normalized = "_" + normalized

    # Step 4: Truncate to 64 characters
    if len(normalized) > 64:
        normalized = normalized[:64]

    # Step 5: Ensure not empty
    if not normalized:
        normalized = "_unnamed_function"

    return normalized


def _resolve_ref(ref: str, root_schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Resolve $ref or ref references
    
    Args:
        ref: Reference path, e.g. "#/definitions/MyType" or "#/$defs/MyType"
        root_schema: Root schema object
        
    Returns:
        Resolved schema, or None on failure
    """
    if not isinstance(ref, str):
        return None
        
    if not ref.startswith('#/'):
        # Try resolving in definitions or $defs
        for key in ["definitions", "$defs"]:
            if key in root_schema and ref in root_schema[key]:
                return root_schema[key][ref]
        return None
    
    path = ref[2:].split('/')
    current = root_schema
    
    for segment in path:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    
    return current if isinstance(current, dict) else None


def _clean_schema_for_claude(schema: Any, root_schema: Optional[Dict[str, Any]] = None, visited: Optional[set] = None) -> Any:
    """
    Sanitize JSON Schema into Claude API supported format (conforming to JSON Schema draft 2020-12)

    Processing logic:
    1. Resolve $ref references
    2. Merge schemas in allOf
    3. Convert anyOf to compatible format
    4. Retain standard JSON Schema types (do not convert to uppercase)
    5. Process array items
    6. Clean fields unsupported by Claude

    Args:
        schema: JSON Schema object
        root_schema: Root schema (for resolving $ref)
        visited: Set of visited objects (prevents circular references)

    Returns:
        Sanitized schema
    """
    # Return non-dict types directly
    if not isinstance(schema, dict):
        return schema

    # Initialize
    if root_schema is None:
        root_schema = schema
    if visited is None:
        visited = set()

    # Prevent circular references
    schema_id = id(schema)
    if schema_id in visited:
        return schema
    visited.add(schema_id)

    # Create copy to avoid mutating original object
    result = {}

    # 1. Process $ref
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], root_schema)
        if resolved:
            result = copy.deepcopy(resolved)
            for key, value in schema.items():
                if key != "$ref":
                    result[key] = value
            schema = result
            result = {}

    # 2. Process allOf (merge all schemas)
    if "allOf" in schema:
        all_of_schemas = schema["allOf"]
        for item in all_of_schemas:
            cleaned_item = _clean_schema_for_claude(item, root_schema, visited)

            if "properties" in cleaned_item:
                if "properties" not in result:
                    result["properties"] = {}
                result["properties"].update(cleaned_item["properties"])

            if "required" in cleaned_item:
                if "required" not in result:
                    result["required"] = []
                result["required"].extend(cleaned_item["required"])

            for key, value in cleaned_item.items():
                if key not in ["properties", "required"]:
                    result[key] = value

        for key, value in schema.items():
            if key not in ["allOf", "properties", "required"]:
                result[key] = value
            elif key in ["properties", "required"] and key not in result:
                result[key] = value
    else:
        result = dict(schema)

    # 3. Process type array (e.g. ["string", "null"])
    if "type" in result:
        type_value = result["type"]
        if isinstance(type_value, list):
            # Claude supports type arrays, keep unchanged
            pass

    # 4. Process array items
    if result.get("type") == "array":
        if "items" not in result:
            result["items"] = {}
        elif isinstance(result["items"], list):
            # Tuple definition: check if all element types are identical
            tuple_items = result["items"]
            first_type = tuple_items[0].get("type") if tuple_items else None
            is_homogeneous = all(item.get("type") == first_type for item in tuple_items)

            if is_homogeneous and first_type:
                result["items"] = _clean_schema_for_claude(tuple_items[0], root_schema, visited)
            else:
                # Heterogeneous tuple: represent with anyOf
                result["items"] = {
                    "anyOf": [_clean_schema_for_claude(item, root_schema, visited) for item in tuple_items]
                }
        else:
            result["items"] = _clean_schema_for_claude(result["items"], root_schema, visited)

    # 5. Process anyOf (keep anyOf, clean recursively)
    if "anyOf" in result:
        result["anyOf"] = [_clean_schema_for_claude(item, root_schema, visited) for item in result["anyOf"]]

    # 6. Clean fields unsupported by Claude (per JSON Schema 2020-12)
    # Claude API is strict on certain fields; remove fields that cause issues
    unsupported_keys = {
        "title", "$schema", "strict",
        "additionalItems",  # Deprecated field, use items instead
        "exclusiveMaximum", "exclusiveMinimum",  # In 2020-12 these should be numeric rather than boolean
        "$defs", "definitions",  # Remove definitions fields to avoid conflicts
        "example", "examples", "readOnly", "writeOnly",
        "const",  # const may cause issues
        "contentEncoding", "contentMediaType",
        "oneOf",  # oneOf may cause issues, replaced by anyOf
        "patternProperties", "dependencies", "propertyNames",  # Unsupported by Google API
    }

    for key in list(result.keys()):
        if key in unsupported_keys:
            del result[key]

    # Recursively process additionalProperties if present
    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _clean_schema_for_claude(result["additionalProperties"], root_schema, visited)

    # 7. Recursively process properties
    if "properties" in result:
        cleaned_props = {}
        for prop_name, prop_schema in result["properties"].items():
            cleaned_props[prop_name] = _clean_schema_for_claude(prop_schema, root_schema, visited)
        result["properties"] = cleaned_props

    # 8. Ensure type field exists if properties are present
    if "properties" in result and "type" not in result:
        result["type"] = "object"

    # 9. Deduplicate required array
    if "required" in result and isinstance(result["required"], list):
        result["required"] = list(dict.fromkeys(result["required"]))

    return result


def _clean_schema_for_gemini(schema: Any, root_schema: Optional[Dict[str, Any]] = None, visited: Optional[set] = None) -> Any:
    """
    Sanitize JSON Schema to Gemini-compatible format

    Reference transformOpenApiSchemaToGemini implementation

    Processing logic:
    1. Resolve $ref references
    2. Merge schemas in allOf
    3. Convert anyOf to enum (if possible)
    4. Type mapping (string -> STRING)
    5. Process ARRAY items (including Tuples)
    6. Move default values to description
    7. Clean unsupported fields

    Args:
        schema: JSON Schema object
        root_schema: Root schema (for resolving $ref)
        visited: Set of visited objects (prevents circular references)

    Returns:
        Sanitized schema
    """
    # Return non-dict types directly
    if not isinstance(schema, dict):
        return schema
    
    # Initialize
    if root_schema is None:
        root_schema = schema
    if visited is None:
        visited = set()
    
    # Prevent circular references
    schema_id = id(schema)
    if schema_id in visited:
        return schema
    visited.add(schema_id)
    
    # Create copy to avoid mutating original object
    result = {}
    
    # 1. Process $ref or ref
    ref_key = "$ref" if "$ref" in schema else ("ref" if "ref" in schema else None)
    if ref_key:
        resolved = _resolve_ref(schema[ref_key], root_schema)
        if resolved:
            # Detect circular reference
            resolved_id = id(resolved)
            if resolved_id in visited:
                return {"type": "OBJECT", "description": "(circular reference)"}
            
            visited.add(resolved_id)
            # Merge resolved schema
            merged = dict(resolved)
            
            # Important: Per Gemini API constraints, only description and default may coexist with ref
            # Other fields (type, properties, etc.) must be dropped to prevent 400 errors
            for key in ["description", "default"]:
                if key in schema:
                    merged[key] = schema[key]
            
            schema = merged
            result = {}
    
    # 2. Process allOf (merge all schemas)
    if "allOf" in schema:
        all_of_schemas = schema["allOf"]
        for item in all_of_schemas:
            cleaned_item = _clean_schema_for_gemini(item, root_schema, visited)
            
            # Merge properties
            if "properties" in cleaned_item:
                if "properties" not in result:
                    result["properties"] = {}
                result["properties"].update(cleaned_item["properties"])
            
            # Merge required
            if "required" in cleaned_item:
                if "required" not in result:
                    result["required"] = []
                result["required"].extend(cleaned_item["required"])
            
            # Merge other fields (simple override)
            for key, value in cleaned_item.items():
                if key not in ["properties", "required"]:
                    result[key] = value
        
        # Copy other fields
        for key, value in schema.items():
            if key not in ["allOf", "properties", "required"]:
                result[key] = value
            elif key in ["properties", "required"] and key not in result:
                result[key] = value
    else:
        # Copy all fields
        result = dict(schema)
    
    # 3. Type mapping (convert to uppercase)
    # Note: Gemini API type field must be a string, not an array
    if "type" in result:
        type_value = result["type"]

        # If type is a list, extract primary non-null type
        if isinstance(type_value, list):
            primary_type = next((t for t in type_value if t != "null"), None)
            type_value = primary_type if primary_type else "STRING"  # Default to STRING

        # Type mapping
        type_map = {
            "string": "STRING",
            "number": "NUMBER",
            "integer": "INTEGER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }

        if isinstance(type_value, str) and type_value.lower() in type_map:
            # Ensure result["type"] is string not list
            result["type"] = type_map[type_value.lower()]
        else:
            # Unknown type, remove field
            del result["type"]
    
    # 4. Process ARRAY items
    if result.get("type") == "ARRAY":
        if "items" not in result:
            # No items specified, allow any type by default
            result["items"] = {}
        elif isinstance(result["items"], list):
            # Tuple definition (items is an array)
            tuple_items = result["items"]
            
            # Extract type information for description
            tuple_types = [item.get("type", "any") for item in tuple_items]
            tuple_desc = f"(Tuple: [{', '.join(tuple_types)}])"
            
            original_desc = result.get("description", "")
            result["description"] = f"{original_desc} {tuple_desc}".strip()
            
            # Check if all element types are identical
            first_type = tuple_items[0].get("type") if tuple_items else None
            is_homogeneous = all(item.get("type") == first_type for item in tuple_items)
            
            if is_homogeneous and first_type:
                # Homogeneous tuple: convert to List<Type>
                result["items"] = _clean_schema_for_gemini(tuple_items[0], root_schema, visited)
            else:
                # Heterogeneous tuple: unsupported by Gemini, set to {}
                result["items"] = {}
        else:
            # Recursively process items
            result["items"] = _clean_schema_for_gemini(result["items"], root_schema, visited)
    
    # 5. Process anyOf (attempt enum conversion)
    if "anyOf" in result:
        any_of_schemas = result["anyOf"]
        
        # Recursively process each schema
        cleaned_any_of = [_clean_schema_for_gemini(item, root_schema, visited) for item in any_of_schemas]
        
        # Attempt extracting enum
        if all("const" in item for item in cleaned_any_of):
            enum_values = [
                str(item["const"]) 
                for item in cleaned_any_of 
                if item.get("const") not in ["", None]
            ]
            if enum_values:
                result["type"] = "STRING"
                result["enum"] = enum_values
        elif "type" not in result:
            # If not enum, use first valid type definition
            first_valid = next((item for item in cleaned_any_of if item.get("type") or item.get("enum")), None)
            if first_valid:
                result.update(first_valid)
        
        # Remove anyOf
        del result["anyOf"]
    
    # 6. Move default values to description
    if "default" in result:
        default_value = result["default"]
        original_desc = result.get("description", "")
        result["description"] = f"{original_desc} (Default: {json.dumps(default_value)})".strip()
        del result["default"]
    
    # 7. Clean unsupported fields
    unsupported_keys = {
        "title", "$schema", "$ref", "ref", "strict", "exclusiveMaximum",
        "exclusiveMinimum", "additionalProperties", "oneOf", "allOf",
        "$defs", "definitions", "example", "examples", "readOnly",
        "writeOnly", "const", "additionalItems", "contains",
        "patternProperties", "dependencies", "propertyNames",
        "if", "then", "else", "contentEncoding", "contentMediaType"
    }
    
    for key in list(result.keys()):
        if key in unsupported_keys:
            del result[key]
    
    # 8. Recursively process properties
    if "properties" in result:
        cleaned_props = {}
        for prop_name, prop_schema in result["properties"].items():
            cleaned_props[prop_name] = _clean_schema_for_gemini(prop_schema, root_schema, visited)
        result["properties"] = cleaned_props
    
    # 9. Ensure type field exists if properties are present
    if "properties" in result and "type" not in result:
        result["type"] = "OBJECT"
    
    # 10. Deduplicate required array
    if "required" in result and isinstance(result["required"], list):
        result["required"] = list(dict.fromkeys(result["required"]))  # Deduplicate preserving order

    # Gemini OpenAPI spec requires enum elements to be string
    if "enum" in result:
        enum_val = result.get("enum")
        if isinstance(enum_val, list):
            if result.get("type") == "BOOLEAN" or any(isinstance(x, bool) for x in enum_val):
                result.pop("enum", None)
            else:
                result["enum"] = [str(x) for x in enum_val]

    return result


def _append_schema_hint(schema: Dict[str, Any], hint: str) -> None:
    """Move incompatible validation constraints into description to avoid upstream rejection."""
    if not hint:
        return
    desc = schema.get("description")
    schema["description"] = f"{desc} ({hint})" if desc else hint


def _clean_schema_for_parameters_json_schema(
    schema: Any,
    root_schema: Optional[Dict[str, Any]] = None,
    visited: Optional[set] = None,
) -> Any:
    """
    Sanitize JSON Schema for use in Gemini CLI internal API's parametersJsonSchema.

    Code Assist's internal interface aligns with official Gemini CLI: tool parameters reside in
    parametersJsonSchema and preserve JSON Schema lowercase type.
    """
    if not isinstance(schema, dict):
        return schema

    if root_schema is None:
        root_schema = schema
    if visited is None:
        visited = set()

    schema_id = id(schema)
    if schema_id in visited:
        return {"type": "object", "description": "(circular reference)"}
    visited.add(schema_id)

    result: Dict[str, Any]

    ref_key = "$ref" if "$ref" in schema else ("ref" if "ref" in schema else None)
    if ref_key:
        resolved = _resolve_ref(schema[ref_key], root_schema)
        if resolved:
            result = copy.deepcopy(resolved)
            for key in ("description", "default"):
                if key in schema:
                    result[key] = schema[key]
            schema = result

    if "allOf" in schema:
        result = {}
        for item in schema.get("allOf") or []:
            cleaned_item = _clean_schema_for_parameters_json_schema(item, root_schema, visited)
            if not isinstance(cleaned_item, dict):
                continue
            if "properties" in cleaned_item:
                result.setdefault("properties", {}).update(cleaned_item["properties"])
            if "required" in cleaned_item:
                result.setdefault("required", []).extend(cleaned_item["required"])
            for key, value in cleaned_item.items():
                if key not in ("properties", "required"):
                    result[key] = value
        for key, value in schema.items():
            if key not in ("allOf", "properties", "required"):
                result[key] = value
            elif key in ("properties", "required") and key not in result:
                result[key] = value
    else:
        result = dict(schema)

    if "type" in result:
        type_value = result["type"]
        if isinstance(type_value, list):
            non_null_types = [t for t in type_value if isinstance(t, str) and t.lower() != "null"]
            if non_null_types:
                result["type"] = non_null_types[0]
                if "null" in [str(t).lower() for t in type_value]:
                    _append_schema_hint(result, "nullable")
            else:
                result["type"] = "string"
        elif isinstance(type_value, str):
            lower_type = type_value.lower()
            if lower_type in {"string", "number", "integer", "boolean", "array", "object", "null"}:
                result["type"] = "string" if lower_type == "null" else lower_type
            else:
                del result["type"]

    if "anyOf" in result or "oneOf" in result:
        union_key = "anyOf" if "anyOf" in result else "oneOf"
        union_items = result.get(union_key) or []
        cleaned_items = [
            item for item in (
                _clean_schema_for_parameters_json_schema(item, root_schema, visited)
                for item in union_items
            )
            if isinstance(item, dict)
        ]
        enum_values = [
            item.get("const")
            for item in union_items
            if isinstance(item, dict) and item.get("const") not in ("", None)
        ]
        if enum_values and len(enum_values) == len(union_items):
            result["type"] = "string"
            result["enum"] = [str(v) for v in enum_values]
        else:
            preferred = next(
                (
                    item for item in cleaned_items
                    if item.get("type") in ("object", "array") or item.get("properties")
                ),
                None,
            )
            if preferred is None:
                preferred = next((item for item in cleaned_items if item.get("type") or item.get("enum")), None)
            if preferred:
                existing_description = result.get("description")
                result.update(preferred)
                if existing_description:
                    _append_schema_hint(result, existing_description)
        result.pop("anyOf", None)
        result.pop("oneOf", None)

    if result.get("type") == "array":
        items = result.get("items")
        if isinstance(items, list):
            if items:
                result["items"] = _clean_schema_for_parameters_json_schema(items[0], root_schema, visited)
                _append_schema_hint(result, "tuple schema simplified")
            else:
                result.pop("items", None)
        elif isinstance(items, dict):
            result["items"] = _clean_schema_for_parameters_json_schema(items, root_schema, visited)

    validation_keys = {
        "default", "minLength", "maxLength", "minimum", "maximum",
        "minItems", "maxItems", "pattern", "format", "uniqueItems",
    }
    for key in list(result.keys()):
        if key in validation_keys:
            value = result.pop(key)
            if value not in (None, "", {}, []):
                _append_schema_hint(result, f"{key}: {json.dumps(value, ensure_ascii=False)}")

    unsupported_keys = {
        "title", "$schema", "$id", "$ref", "ref", "strict",
        "exclusiveMaximum", "exclusiveMinimum", "additionalProperties",
        "allOf", "anyOf", "oneOf", "$defs", "definitions", "example",
        "examples", "readOnly", "writeOnly", "const", "additionalItems",
        "contains", "patternProperties", "dependencies", "propertyNames",
        "if", "then", "else", "contentEncoding", "contentMediaType",
    }
    for key in list(result.keys()):
        if key in unsupported_keys or key.startswith("x-"):
            del result[key]

    nullable_props = set()
    if "properties" in result and isinstance(result["properties"], dict):
        cleaned_props = {}
        for prop_name, prop_schema in result["properties"].items():
            if isinstance(prop_schema, dict):
                prop_type = prop_schema.get("type")
                if isinstance(prop_type, list) and any(str(t).lower() == "null" for t in prop_type):
                    nullable_props.add(prop_name)
            cleaned_props[prop_name] = _clean_schema_for_parameters_json_schema(prop_schema, root_schema, visited)
        result["properties"] = cleaned_props

    if "properties" in result and "type" not in result:
        result["type"] = "object"

    if "required" in result and isinstance(result["required"], list):
        prop_names = set(result.get("properties", {}).keys()) if isinstance(result.get("properties"), dict) else None
        required = []
        for item in result["required"]:
            if not isinstance(item, str):
                continue
            if prop_names is not None and item not in prop_names:
                continue
            if item in nullable_props:
                continue
            if item not in required:
                required.append(item)
        if required:
            result["required"] = required
        else:
            result.pop("required", None)

    # Gemini OpenAPI spec requires enum elements to be string
    if "enum" in result:
        enum_val = result.get("enum")
        if isinstance(enum_val, list):
            if result.get("type") == "boolean" or any(isinstance(x, bool) for x in enum_val):
                result.pop("enum", None)
            else:
                result["enum"] = [str(x) for x in enum_val]

    return result


def fix_tool_call_args_types(
    args: Dict[str, Any],
    parameters_schema: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Fix function call argument types according to tool parameter schema
    
    E.g., convert string "5" to integer 5 based on schema type definition
    
    Args:
        args: Function call arguments dictionary
        parameters_schema: Parameters schema from tool definition
        
    Returns:
        Arguments dictionary with corrected types
    """
    if not args or not parameters_schema:
        return args
    
    properties = parameters_schema.get("properties", {})
    if not properties:
        return args
    
    fixed_args = {}
    for key, value in args.items():
        if key not in properties:
            # Parameter not in schema, keep as-is
            fixed_args[key] = value
            continue
        
        param_schema = properties[key]
        param_type = param_schema.get("type")
        
        # Fix parameter value based on schema type
        if param_type == "number" or param_type == "integer":
            # If value is string, attempt conversion to number
            if isinstance(value, str):
                try:
                    if param_type == "integer":
                        fixed_args[key] = int(value)
                    else:
                        # Attempt float conversion, retain int if whole number
                        num_value = float(value)
                        fixed_args[key] = int(num_value) if num_value.is_integer() else num_value
                    log.debug(f"[OPENAI2GEMINI] Fixed argument type: {key} '{value}' -> {fixed_args[key]} ({param_type})")
                except (ValueError, AttributeError):
                    # Conversion failed, keep as-is
                    fixed_args[key] = value
                    log.warning(f"[OPENAI2GEMINI] Unable to convert argument {key} value '{value}' to {param_type}")
            else:
                fixed_args[key] = value
        elif param_type == "boolean":
            # If value is string, convert to boolean
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    fixed_args[key] = True
                elif value.lower() in ("false", "0", "no"):
                    fixed_args[key] = False
                else:
                    fixed_args[key] = value
                if fixed_args[key] != value:
                    log.debug(f"[OPENAI2GEMINI] Fixed argument type: {key} '{value}' -> {fixed_args[key]} (boolean)")
            else:
                fixed_args[key] = value
        elif param_type == "string":
            # If value is not string, convert to string
            if not isinstance(value, str):
                fixed_args[key] = str(value)
                log.debug(f"[OPENAI2GEMINI] Fixed argument type: {key} {value} -> '{fixed_args[key]}' (string)")
            else:
                fixed_args[key] = value
        else:
            # Other types (array, object, etc.) kept as-is
            fixed_args[key] = value
    
    return fixed_args


def convert_openai_tools_to_gemini(openai_tools: List, model: str = "") -> List[Dict[str, Any]]:
    """
    Convert OpenAI tools format to Gemini functionDeclarations format

    Args:
        openai_tools: OpenAI format tools list (dict or Pydantic model)
        model: Model name (used to check if Claude model)

    Returns:
        Gemini format tools list
    """
    if not openai_tools:
        return []

    # Determine if Claude model
    is_claude_model = "claude" in model.lower()

    function_declarations = []

    for tool in openai_tools:
        if tool.get("type") != "function":
            log.warning(f"Skipping non-function tool type: {tool.get('type')}")
            continue

        function = tool.get("function")
        if not function:
            log.warning("Tool missing 'function' field")
            continue

        # Retrieve and normalize function name
        original_name = function.get("name")
        if not original_name:
            log.warning("Tool missing 'name' field, using default")
            original_name = "_unnamed_function"

        normalized_name = _normalize_function_name(original_name)

        # Log if function name was modified
        if normalized_name != original_name:
            log.debug(f"Function name normalized: '{original_name}' -> '{normalized_name}'")

        # Construct Gemini function declaration
        declaration = {
            "name": normalized_name,
            "description": function.get("description", ""),
        }

        # Add parameters (if any) - Gemini CLI internal API uses parametersJsonSchema
        if "parameters" in function:
            if is_claude_model:
                cleaned_params = _clean_schema_for_parameters_json_schema(function["parameters"])
                log.debug(f"[OPENAI2GEMINI] Using Claude schema cleaning for tool: {normalized_name}")
            else:
                cleaned_params = _clean_schema_for_parameters_json_schema(function["parameters"])

            if cleaned_params:
                declaration["parametersJsonSchema"] = cleaned_params
            elif is_claude_model:
                declaration["parametersJsonSchema"] = {"type": "object", "properties": {}}
        elif is_claude_model:
            declaration["parametersJsonSchema"] = {"type": "object", "properties": {}}

        function_declarations.append(declaration)

    if not function_declarations:
        return []

    # Gemini format: tools array containing functionDeclarations
    return [{"functionDeclarations": function_declarations}]


def convert_tool_choice_to_tool_config(
    tool_choice: Union[str, Dict[str, Any]],
    tool_names: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Convert OpenAI tool_choice to Gemini toolConfig

    Args:
        tool_choice: OpenAI format tool_choice

    Returns:
        Gemini format toolConfig
    """
    if isinstance(tool_choice, str):
        if tool_choice == "auto":
            return {"functionCallingConfig": {"mode": "AUTO"}}
        elif tool_choice == "none":
            return {"functionCallingConfig": {"mode": "NONE"}}
        elif tool_choice == "required":
            if tool_names is not None and not tool_names:
                raise ValueError("tool_choice 'required' needs at least one function tool")
            return {"functionCallingConfig": {"mode": "ANY"}}
    elif isinstance(tool_choice, dict):
        # {"type": "function", "function": {"name": "my_function"}}
        function = tool_choice.get("function")
        if tool_choice.get("type") == "function" and isinstance(function, dict):
            function_name = function.get("name")
            if isinstance(function_name, str) and function_name:
                if tool_names is not None and function_name not in tool_names:
                    raise ValueError(
                        f"tool_choice refers to an undeclared function: {function_name}"
                    )
                return {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": [_normalize_function_name(function_name)],
                    }
                }

    raise ValueError("Unsupported tool_choice for Antigravity")


def _reverse_transform_value(value: Any) -> Any:
    """
    Convert values back to original types (Gemini may stringify values)

    Only handles common boolean/null stringification in Gemini tool arguments;
    avoids heuristic number conversion to prevent converting arguments declared
    as string in schema into integers erroneously.
    
    Reference reverseTransformValue implementation
    
    Args:
        value: Value to convert
        
    Returns:
        Converted value
    """
    if not isinstance(value, str):
        return value
    
    # Boolean values
    if value == 'true':
        return True
    if value == 'false':
        return False
    
    # null
    if value == 'null':
        return None
    
    # Otherwise keep string
    return value


def _reverse_transform_args(args: Any) -> Any:
    """
    Recursively convert function arguments, restoring strings to original types
    
    Reference reverseTransformArgs implementation
    
    Args:
        args: Function arguments (dict, list, or other types)
        
    Returns:
        Converted arguments
    """
    if not isinstance(args, (dict, list)):
        return args
    
    if isinstance(args, list):
        return [_reverse_transform_args(item) for item in args]
    
    # Process dict
    result = {}
    for key, value in args.items():
        if isinstance(value, (dict, list)):
            result[key] = _reverse_transform_args(value)
        else:
            result[key] = _reverse_transform_value(value)
    
    return result


def extract_tool_calls_from_parts(
    parts: List[Dict[str, Any]], is_streaming: bool = False
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Extract tool calls and text content from Gemini response parts

    Args:
        parts: Gemini response parts list
        is_streaming: Whether streaming response (requires index field)

    Returns:
        (tool_calls, text_content) tuple
    """
    tool_calls = []
    text_content = ""

    for idx, part in enumerate(parts):
        # Check if function call
        if "functionCall" in part:
            function_call = part["functionCall"]
            # Get original ID or generate new ID
            original_id = function_call.get("id") or f"call_{uuid.uuid4().hex[:24]}"
            # Get arguments and convert types
            args = function_call.get("args", {})
            # Convert stringified values back to original types
            args = _reverse_transform_args(args)

            tool_call = {
                "id": original_id,
                "type": "function",
                "function": {
                    "name": function_call.get("name", "nameless_function"),
                    "arguments": json.dumps(args),
                },
            }
            # Streaming response requires index field
            if is_streaming:
                tool_call["index"] = idx
            tool_calls.append(tool_call)

        # Extract text content (excluding thinking tokens)
        elif "text" in part and not part.get("thought", False):
            text = part["text"]
            if (
                is_skip_thought_signature_placeholder(part)
                or is_internal_placeholder_text(text)
            ):
                continue
            text_content += text

    return tool_calls, text_content


def extract_images_from_content(content: Any) -> Dict[str, Any]:
    """
    Extract text and images from OpenAI content
    
    Args:
        content: OpenAI message content (string or list)
    
    Returns:
        Dictionary containing text and images
    """
    result = {"text": "", "images": []}

    if isinstance(content, str):
        result["text"] = content
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    result["text"] += item.get("text", "")
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    # Parse data:image/png;base64,xxx format
                    if image_url.startswith("data:image/"):
                        match = re.match(r"^data:image/(\w+);base64,(.+)$", image_url)
                        if match:
                            mime_type = match.group(1)
                            base64_data = match.group(2)
                            result["images"].append({
                                "inlineData": {
                                    "mimeType": f"image/{mime_type}",
                                    "data": base64_data
                                }
                            })

    return result


def _sanitize_openai_roundtrip_signatures(contents: List[Dict[str, Any]]) -> None:
    """
    OpenAI-compatible clients may round-trip Gemini thinking signatures through
    fields we do not fully control. Keep tool calls on the safe bypass sentinel
    and drop signatures everywhere else to avoid Corrupted thought signature.
    """
    for content in contents:
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue

        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue

            sanitized_part = part.copy()
            if "thoughtSignature" in sanitized_part:
                if "functionCall" in sanitized_part or "function_call" in sanitized_part:
                    sanitized_part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE_VALIDATOR
                else:
                    sanitized_part.pop("thoughtSignature", None)

            if sanitized_part.get("thought") is True and not sanitized_part.get("thoughtSignature"):
                sanitized_part.pop("thought", None)

            parts[index] = sanitized_part


def _convert_openai_message_content(role: str, content: Any) -> List[Dict[str, Any]]:
    """Convert supported Chat Completions content without silently losing parts."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        raise ValueError(f"{role} message content must be text or content parts")

    parts = []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError(f"{role} message contains an invalid content part")
        part_type = part.get("type")
        if part_type == "text" or (role == "assistant" and part_type == "refusal"):
            value = part.get(part_type)
            if not isinstance(value, str):
                raise ValueError(f"{role} {part_type} content part must contain a string")
            if value:
                parts.append({"text": value})
        elif role == "user" and part_type == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if not isinstance(url, str) or not url.startswith("data:image/"):
                raise ValueError(
                    "Antigravity requires image_url content as a base64 image data URL"
                )
            header, separator, encoded = url.partition(",")
            if not separator or not header.endswith(";base64"):
                raise ValueError("Invalid base64 image data URL")
            try:
                base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("Invalid base64 image data URL") from exc
            parts.append({"inlineData": {"mimeType": header[5:-7], "data": encoded}})
        else:
            raise ValueError(
                f"{role} content part type {part_type!r} is unsupported by Antigravity"
            )
    return parts


async def convert_openai_to_gemini_request(openai_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert OpenAI request body to Gemini request body

    Note: This function performs basic conversion only; does not include normalize_antigravity_request processing
    (e.g., thinking config, search tools, parameter clamping, etc.)

    Args:
        openai_request: OpenAI request body dict, containing:
            - messages: Message list
            - temperature, top_p, max_tokens, stop generation parameters
            - tools, tool_choice (optional)
            - response_format (optional)

    Returns:
        Gemini request body dict, containing:
            - contents: Converted message contents
            - generationConfig: Generation configuration
            - systemInstruction: System instructions (if any)
            - tools, toolConfig (if any)
    """
    # Keep instruction roles out of Gemini contents.
    openai_request = await merge_system_messages(openai_request)

    contents = []

    # Extract messages list
    messages = openai_request.get("messages", [])

    # Look up tool name by ID, not rejecting early on incomplete or duplicate history.
    tool_call_mapping = {}
    for message in messages:
        if message.get("role") == "assistant":
            for tool_call in message.get("tool_calls") or []:
                encoded_id = tool_call.get("id", "")
                if encoded_id:
                    original_id, _ = decode_tool_id_and_signature(encoded_id)
                    func_name = tool_call.get("function", {}).get("name") or ""
                    tool_call_mapping[encoded_id] = (func_name, original_id)

    # Collect tool declarations once, validate names, and keep parameter schemas to fix history types.
    tool_schemas = {}
    normalized_names = set()
    for tool in openai_request.get("tools") or []:
        if tool.get("type") == "function":
            function = tool["function"]
            func_name = function["name"]
            normalized_name = _normalize_function_name(func_name)
            if normalized_name in normalized_names:
                raise ValueError("Function tool names collide after Antigravity normalization")
            normalized_names.add(normalized_name)
            tool_schemas[func_name] = function.get("parameters", {})
    tool_names = set(tool_schemas)

    # Accumulate functionResponse parts for consecutive tool messages
    pending_tool_parts = []

    def flush_pending_tool_parts():
        """Append accumulated tool parts as a single contents entry"""
        nonlocal pending_tool_parts
        if pending_tool_parts:
            contents.append({
                "role": "user",
                "parts": pending_tool_parts
            })
            pending_tool_parts = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        # Handle tool messages (tool role) - accumulate to pending_tool_parts
        if role == "tool":
            tool_call_id = message.get("tool_call_id", "")
            original_id, _ = decode_tool_id_and_signature(tool_call_id)
            func_name, original_id = tool_call_mapping.get(
                tool_call_id, (message.get("name"), original_id)
            )
            if not func_name:
                func_name = "unknown_function"
                log.warning(f"Tool message missing function name for tool_call_id={tool_call_id}, using default: {func_name}")
            func_name = _normalize_function_name(func_name)

            # OpenAI also permits an array of text content parts for tool results.
            if isinstance(content, list):
                if not all(
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                    for part in content
                ):
                    raise ValueError("Tool message content may only contain text parts")
                content = "".join(part.get("text", "") for part in content)
            elif not isinstance(content, str):
                raise ValueError("Tool message content must be text or text parts")

            # Parse response data
            try:
                response_data = json.loads(content)
            except json.JSONDecodeError:
                response_data = {"result": content}

            # Ensure response_data is a dict (Gemini API requires response to be an object)
            if not isinstance(response_data, dict):
                response_data = {"result": response_data}

            # Accumulate functionResponse part without appending immediately
            pending_tool_parts.append({
                "functionResponse": {
                    "id": original_id,
                    "name": func_name,
                    "response": response_data
                }
            })
            continue

        # Flush accumulated tool parts when encountering non-tool message
        flush_pending_tool_parts()

        if role not in ("user", "assistant"):
            raise ValueError(f"Unsupported message role: {role}")

        parts = _convert_openai_message_content(role, content)
        if role == "assistant" and not parts and message.get("refusal"):
            parts = [{"text": message["refusal"]}]

        # Map OpenAI role to Gemini role
        gemini_role = "model" if role == "assistant" else "user"

        # Check if tool_calls present
        tool_calls = message.get("tool_calls")
        if tool_calls:
            if role != "assistant":
                raise ValueError("Only assistant messages may contain tool_calls")

            for tool_call in tool_calls:
                encoded_id = tool_call.get("id", "")
                try:
                    function = tool_call["function"]
                    args = (
                        json.loads(function["arguments"])
                        if isinstance(function["arguments"], str)
                        else function["arguments"]
                    )
                    if not isinstance(args, dict):
                        # Gemini functionCall.args must be an object; non-objects use fallback recovery
                        raise ValueError("tool call arguments must be a JSON object")
                    func_name = function["name"]
                except (ValueError, KeyError) as exc:
                    # Upstream fault tolerance: preserve call, recover first JSON object, fallback to empty args.
                    function = tool_call.get("function") or {}
                    func_name = function.get("name")
                    if not func_name:
                        log.error(f"Failed to parse tool call (dropped, no name): {exc}")
                        continue
                    args = {}
                    raw_args = function.get("arguments", "")
                    if isinstance(raw_args, str) and raw_args:
                        try:
                            recovered, _ = json.JSONDecoder().raw_decode(raw_args.lstrip())
                        except ValueError:
                            recovered = None
                        if isinstance(recovered, dict):
                            args = recovered
                    log.warning(
                        f"Failed to parse tool call: {exc} - keeping degraded functionCall "
                        f"name={func_name} args={'partial' if args else 'empty'}"
                    )

                if func_name in tool_schemas:
                    args = fix_tool_call_args_types(args, tool_schemas[func_name])

                original_id, _ = decode_tool_id_and_signature(encoded_id)
                normalized_name = _normalize_function_name(func_name)
                parts.append(
                    {
                        "functionCall": {
                            "id": original_id,
                            "name": normalized_name,
                            "args": args,
                        },
                        # Proxy may rewrite tool_call_id; use skip-validation placeholder to prevent signature corruption.
                        "thoughtSignature": SKIP_THOUGHT_SIGNATURE_VALIDATOR,
                    }
                )
            if not parts:
                continue

        if not parts:
            raise ValueError(f"{role} message has no content representable by Antigravity")
        contents.append({"role": gemini_role, "parts": parts})

    # Flush remaining tool parts after loop (if messages end with tool message)
    flush_pending_tool_parts()
    _sanitize_openai_roundtrip_signatures(contents)

    # Consolidate adjacent contents with identical roles (Gemini requires alternating roles to prevent 0-token empty responses)
    merged_contents = []
    for c in contents:
        if not c.get("parts"):
            continue
        if merged_contents and merged_contents[-1]["role"] == c["role"]:
            merged_contents[-1]["parts"].extend(c["parts"])
        else:
            merged_contents.append(c)
    contents = merged_contents

    # Build generation config
    generation_config = {}
    model = openai_request.get("model", "")

    # Base parameters mapping
    if "temperature" in openai_request:
        generation_config["temperature"] = openai_request["temperature"]
    if "top_p" in openai_request:
        generation_config["topP"] = openai_request["top_p"]
    if "top_k" in openai_request:
        generation_config["topK"] = openai_request["top_k"]
    if "max_tokens" in openai_request or "max_completion_tokens" in openai_request:
        # max_completion_tokens takes precedence over max_tokens
        max_tokens = openai_request.get("max_completion_tokens") or openai_request.get("max_tokens")
        generation_config["maxOutputTokens"] = max_tokens
    if "stop" in openai_request:
        stop = openai_request["stop"]
        generation_config["stopSequences"] = [stop] if isinstance(stop, str) else stop
    if "frequency_penalty" in openai_request:
        generation_config["frequencyPenalty"] = openai_request["frequency_penalty"]
    if "presence_penalty" in openai_request:
        generation_config["presencePenalty"] = openai_request["presence_penalty"]
    if "n" in openai_request:
        generation_config["candidateCount"] = openai_request["n"]
    if "seed" in openai_request:
        generation_config["seed"] = openai_request["seed"]

    # Handle response_format
    if "response_format" in openai_request and openai_request["response_format"]:
        response_format = openai_request["response_format"]
        format_type = response_format.get("type")

        if format_type == "json_schema":
            # JSON Schema mode
            if "json_schema" in response_format and "schema" in response_format["json_schema"]:
                schema = response_format["json_schema"]["schema"]
                # Clean schema
                generation_config["responseSchema"] = _clean_schema_for_gemini(schema)
                generation_config["responseMimeType"] = "application/json"
        elif format_type == "json_object":
            # JSON Object mode
            generation_config["responseMimeType"] = "application/json"
        elif format_type == "text":
            # Text mode
            generation_config["responseMimeType"] = "text/plain"

    # If contents is empty, add default user message
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Please respond according to the system instructions."}]})

    # Build base request
    gemini_request = {
        "contents": contents,
        "generationConfig": generation_config
    }

    # Use systemInstruction if already added by merge_system_messages
    if "systemInstruction" in openai_request:
        gemini_request["systemInstruction"] = openai_request["systemInstruction"]

    # Process tools - pass model argument to choose cleaning strategy by model type
    if "tools" in openai_request and openai_request["tools"]:
        gemini_request["tools"] = convert_openai_tools_to_gemini(openai_request["tools"], model)

    # Process tool_choice
    if "tool_choice" in openai_request and openai_request["tool_choice"]:
        choice = openai_request["tool_choice"]
        if tool_names or choice not in ("auto", "none"):
            gemini_request["toolConfig"] = convert_tool_choice_to_tool_config(choice, tool_names)

    # Pass through image generation size parameter (e.g. "1024x1536")
    if "size" in openai_request and openai_request["size"]:
        gemini_request["size"] = openai_request["size"]

    return gemini_request


def convert_gemini_to_openai_response(
    gemini_response: Union[Dict[str, Any], Any],
    model: str,
    status_code: int = 200
) -> Dict[str, Any]:
    """
    Convert Gemini non-streaming response to OpenAI non-streaming response

    Note: Non-2xx responses are forwarded directly without transformation

    Args:
        gemini_response: Gemini response body (dict or Response object)
        model: Model name
        status_code: HTTP status code (default 200)

    Returns:
        OpenAI format response dict, or original response if non-2xx
    """
    # Return original response directly for non-2xx status
    if not (200 <= status_code < 300):
        if isinstance(gemini_response, dict):
            return gemini_response
        else:
            # If response object, attempt parsing as dict
            try:
                if hasattr(gemini_response, "json"):
                    return gemini_response.json()
                elif hasattr(gemini_response, "body"):
                    body = gemini_response.body
                    if isinstance(body, bytes):
                        return json.loads(body.decode())
                    return json.loads(str(body))
                else:
                    return {"error": str(gemini_response)}
            except Exception:
                return {"error": str(gemini_response)}

    # Ensure dictionary format
    if not isinstance(gemini_response, dict):
        try:
            if hasattr(gemini_response, "json"):
                gemini_response = gemini_response.json()
            elif hasattr(gemini_response, "body"):
                body = gemini_response.body
                if isinstance(body, bytes):
                    gemini_response = json.loads(body.decode())
                else:
                    gemini_response = json.loads(str(body))
            else:
                gemini_response = json.loads(str(gemini_response))
        except Exception:
            return {"error": "Invalid response format"}

    # Unwrap Antigravity response wrapper format
    if "response" in gemini_response:
        gemini_response = gemini_response["response"]

    # Convert to OpenAI format
    choices = []

    for candidate in gemini_response.get("candidates", []):
        role = candidate.get("content", {}).get("role", "assistant")

        # Map Gemini role back to OpenAI role
        if role == "model":
            role = "assistant"

        # Extract and separate thinking tokens and standard content
        parts = candidate.get("content", {}).get("parts", [])

        # Extract tool calls and text content
        tool_calls, text_content = extract_tool_calls_from_parts(parts)

        # Extract multiple content types
        content_parts = []
        reasoning_parts = []
        
        for part in parts:
            # Handle executableCode (code generation)
            if "executableCode" in part:
                exec_code = part["executableCode"]
                lang = exec_code.get("language", "python").lower()
                code = exec_code.get("code", "")
                # Add code block (with newlines for proper Markdown rendering)
                content_parts.append(f"\n```{lang}\n{code}\n```\n")
            
            # Handle codeExecutionResult (execution outcome)
            elif "codeExecutionResult" in part:
                result = part["codeExecutionResult"]
                outcome = result.get("outcome")
                output = result.get("output", "")
                
                if output:
                    label = "output" if outcome == "OUTCOME_OK" else "error"
                    content_parts.append(f"\n```{label}\n{output}\n```\n")
            
            # Handle thought (reasoning content)
            elif (
                part.get("thought", False)
                and "text" in part
                and not is_skip_thought_signature_placeholder(part)
            ):
                reasoning_parts.append(part["text"])
            
            # Handle standard text (non-thought)
            elif "text" in part and not part.get("thought", False):
                # Already handled in extract_tool_calls_from_parts
                pass
            
            # Handle inlineData (images)
            elif "inlineData" in part:
                inline_data = part["inlineData"]
                mime_type = inline_data.get("mimeType", "image/png")
                base64_data = inline_data.get("data", "")
                # Format as Markdown
                content_parts.append(f"![gemini-generated-content](data:{mime_type};base64,{base64_data})")
        
        # Merge all content parts
        if content_parts:
            # Join parts with double newlines ensuring separation between blocks
            additional_content = "\n\n".join(content_parts)
            if text_content:
                text_content = text_content + "\n\n" + additional_content
            else:
                text_content = additional_content
        
        # Merge reasoning content
        reasoning_content = "\n\n".join(reasoning_parts) if reasoning_parts else ""

        # Build message object
        message = {"role": role}

        # Get Gemini finishReason
        gemini_finish_reason = candidate.get("finishReason")
        
        # If tool calls exist
        if tool_calls:
            message["tool_calls"] = tool_calls
            message["content"] = text_content if text_content else None
            # Set to tool_calls only on normal STOP; otherwise retain original finish_reason
            # Prevents returning tool_calls during SAFETY, MAX_TOKENS etc. which causes loops
            if gemini_finish_reason == "STOP":
                finish_reason = "tool_calls"
            else:
                finish_reason = _map_finish_reason(gemini_finish_reason)
        else:
            message["content"] = text_content
            finish_reason = _map_finish_reason(gemini_finish_reason)

        # Add reasoning content (if present)
        if reasoning_content:
            message["reasoning_content"] = reasoning_content

        choices.append({
            "index": candidate.get("index", 0),
            "message": message,
            "finish_reason": finish_reason,
        })

    # Convert usageMetadata
    usage = _convert_usage_metadata(gemini_response.get("usageMetadata"))

    response_data = {
        "id": str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
    }

    if usage:
        response_data["usage"] = usage

    return response_data


def convert_gemini_to_openai_stream(
    gemini_stream_chunk: str,
    model: str,
    response_id: str,
    status_code: int = 200
) -> Optional[str]:
    """
    Convert Gemini streaming response chunk to OpenAI SSE streaming response

    Note: Non-2xx responses are forwarded directly without transformation

    Args:
        gemini_stream_chunk: Gemini stream chunk string (typically "data: {json}")
        model: Model name
        response_id: Consistent response ID for stream
        status_code: HTTP status code (default 200)

    Returns:
        OpenAI SSE format response string (e.g. "data: {json}\n\n"),
        or original content if non-2xx,
        or None on parse failure
    """
    # Return raw content directly for non-2xx status
    if not (200 <= status_code < 300):
        return gemini_stream_chunk

    # Parse Gemini stream chunk
    try:
        # Strip "data: " prefix
        if isinstance(gemini_stream_chunk, bytes):
            if gemini_stream_chunk.startswith(b"data: "):
                payload_str = gemini_stream_chunk[len(b"data: "):].strip().decode("utf-8")
            else:
                payload_str = gemini_stream_chunk.strip().decode("utf-8")
        else:
            if gemini_stream_chunk.startswith("data: "):
                payload_str = gemini_stream_chunk[len("data: "):].strip()
            else:
                payload_str = gemini_stream_chunk.strip()

        # Skip empty chunk
        if not payload_str:
            return None

        # Parse JSON
        gemini_chunk = json.loads(payload_str)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Parse failed, skip chunk
        return None

    # Unwrap Antigravity response wrapper format
    if "response" in gemini_chunk:
        gemini_response = gemini_chunk["response"]
    else:
        gemini_response = gemini_chunk

    # Convert to OpenAI streaming format
    choices = []

    for candidate in gemini_response.get("candidates", []):
        role = candidate.get("content", {}).get("role", "assistant")

        # Map Gemini role back to OpenAI role
        if role == "model":
            role = "assistant"

        # Extract and separate thinking tokens and standard content
        parts = candidate.get("content", {}).get("parts", [])

        # Extract tool calls and text content (streaming requires index)
        tool_calls, text_content = extract_tool_calls_from_parts(parts, is_streaming=True)

        # extract_tool_calls_from_parts returns chunk-local parts index,
        # which is always 0 for parallel calls. Use stream-monotonic index so clients merge them correctly.
        if tool_calls:
            for tool_call, stream_index in zip(
                tool_calls, _next_stream_tool_call_indices(response_id, len(tool_calls))
            ):
                tool_call["index"] = stream_index

        # Extract multiple content types
        content_parts = []
        reasoning_parts = []
        
        for part in parts:
            # Handle executableCode (code generation)
            if "executableCode" in part:
                exec_code = part["executableCode"]
                lang = exec_code.get("language", "python").lower()
                code = exec_code.get("code", "")
                content_parts.append(f"\n```{lang}\n{code}\n```\n")
            
            # Handle codeExecutionResult (execution outcome)
            elif "codeExecutionResult" in part:
                result = part["codeExecutionResult"]
                outcome = result.get("outcome")
                output = result.get("output", "")
                
                if output:
                    label = "output" if outcome == "OUTCOME_OK" else "error"
                    content_parts.append(f"\n```{label}\n{output}\n```\n")
            
            # Handle thought (reasoning content)
            elif (
                part.get("thought", False)
                and "text" in part
                and not is_skip_thought_signature_placeholder(part)
            ):
                reasoning_parts.append(part["text"])
            
            # Handle standard text (non-thought)
            elif "text" in part and not part.get("thought", False):
                # Already handled in extract_tool_calls_from_parts
                pass
            
            # Handle inlineData (images)
            elif "inlineData" in part:
                inline_data = part["inlineData"]
                mime_type = inline_data.get("mimeType", "image/png")
                base64_data = inline_data.get("data", "")
                content_parts.append(f"![gemini-generated-content](data:{mime_type};base64,{base64_data})")
        
        # Merge all content parts
        if content_parts:
            additional_content = "\n\n".join(content_parts)
            if text_content:
                text_content = text_content + "\n\n" + additional_content
            else:
                text_content = additional_content
        
        # Merge reasoning content
        reasoning_content = "\n\n".join(reasoning_parts) if reasoning_parts else ""

        # Build delta object
        delta = {}

        if tool_calls:
            delta["tool_calls"] = tool_calls
            if text_content:
                delta["content"] = text_content
        elif text_content:
            delta["content"] = text_content

        if reasoning_content:
            delta["reasoning_content"] = reasoning_content

        # Get Gemini finishReason
        gemini_finish_reason = candidate.get("finishReason")
        # In streaming, Gemini sets finishReason only in final chunk;
        # intermediate chunks have None finishReason and must return null,
        # otherwise OpenAI-compatible clients stop prematurely after first chunk,
        # causing truncated output with only thoughts or first tool call.
        if gemini_finish_reason:
            finish_reason = _map_finish_reason(gemini_finish_reason)
        else:
            finish_reason = None
        
        # Set to tool_calls only on normal STOP with tool calls present
        # Prevents loops under SAFETY, MAX_TOKENS etc.
        # Note: In streaming, tool_calls usually appear in earlier chunks; trailing chunk is empty,
        # check if stream (response_id) was previously assigned tool call indices (_STREAM_TOOL_INDEX > 0).
        had_tools = bool(tool_calls or _STREAM_TOOL_INDEX.get(response_id, 0) > 0)
        if had_tools and gemini_finish_reason == "STOP":
            finish_reason = "tool_calls"

        choices.append({
            "index": candidate.get("index", 0),
            "delta": delta,
            "finish_reason": finish_reason,
        })

    # Stream finished; reclaim tool index tracking for response_id
    if any(choice.get("finish_reason") for choice in choices):
        _STREAM_TOOL_INDEX.pop(response_id, None)

    # Convert usageMetadata (only present at end of stream)
    usage = _convert_usage_metadata(gemini_response.get("usageMetadata"))

    # Build OpenAI stream response
    response_data = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
    }

    # Add usage only when usage data and finish_reason are present
    if usage:
        has_finish_reason = any(choice.get("finish_reason") for choice in choices)
        if has_finish_reason:
            response_data["usage"] = usage

    # Format as SSE: "data: {json}\n\n"
    return f"data: {json.dumps(response_data)}\n\n"
