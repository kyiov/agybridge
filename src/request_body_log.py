"""
Request Body Logging Service (Disk JSON storage)
- Controlled by request_log_enabled configuration
- Stored under data/request_logs/<YYYY-MM-DD>/<timestamp_ms>_<request_id>.json
- usage_log database row stores the relative path index in request_log_file
"""

import json
import os
import shutil
import time
from typing import Any, Dict, Optional

import aiofiles

from log import log

REQUEST_LOG_DIR = os.path.join("data", "request_logs")

# Sensitive headers redacted from persistence (lowercase)
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-goog-api-key", "x-api-key"}


def _sanitize_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    safe: Dict[str, str] = {}
    for key, value in (headers or {}).items():
        if str(key).lower() in _SENSITIVE_HEADERS:
            safe[key] = "[REDACTED]"
        else:
            safe[str(key)] = str(value)
    return safe


async def record_request_body(
    *,
    request_id: str,
    model_name: str,
    upstream_model_name: str,
    credential_email: str,
    is_stream: bool,
    status_code: int,
    url: str,
    headers: Optional[Dict[str, str]],
    payload: Any,
    response_body: str = "",
    error_message: str = "",
) -> Optional[str]:
    """
    Write detailed request/response payload to disk as JSON.
    Returns relative path index, or None on failure. Non-blocking to main workflow.
    """
    ts = time.time()
    date_dir = time.strftime("%Y-%m-%d", time.localtime(ts))
    rel_dir = os.path.join(REQUEST_LOG_DIR, date_dir)
    file_name = f"{int(ts * 1000)}_{request_id or 'unknown'}.json"
    rel_path = f"{date_dir}/{file_name}"
    full_path = os.path.join(rel_dir, file_name)

    entry = {
        "created_at": ts,
        "request_id": request_id,
        "model_name": model_name,
        "upstream_model_name": upstream_model_name,
        "credential_email": credential_email,
        "is_stream": is_stream,
        "status_code": status_code,
        "url": url,
        "request_headers": _sanitize_headers(headers),
        "request_body": payload,
        "response_body": response_body,
        "error_message": error_message,
    }

    try:
        os.makedirs(rel_dir, exist_ok=True)
        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(entry, ensure_ascii=False, indent=2))
        return rel_path
    except Exception as e:
        log.warning(f"Failed to write request body log: {e}")
        return None


def _resolve_path(rel_path: str) -> Optional[str]:
    """Resolve database relative path index to absolute disk path, preventing traversal."""
    if not rel_path:
        return None
    normalized = rel_path.replace("\\", "/")
    root = os.path.normpath(REQUEST_LOG_DIR)
    full = os.path.normpath(os.path.join(root, normalized))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def read_request_body_log(rel_path: str) -> Optional[Dict[str, Any]]:
    """Read detailed payload log from disk. Returns None if absent or corrupt."""
    full = _resolve_path(rel_path)
    if not full or not os.path.isfile(full):
        return None
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def clear_request_body_logs(before_timestamp: Optional[float] = None) -> int:
    """
    Delete detailed log files, returning deleted count.
    - before_timestamp=None: Clears all logs
    - otherwise: Deletes files older than the timestamp
    """
    root = REQUEST_LOG_DIR
    if not os.path.isdir(root):
        return 0

    if before_timestamp is None:
        count = 0
        for _dirpath, _dirnames, filenames in os.walk(root):
            count += len(filenames)
        try:
            shutil.rmtree(root, ignore_errors=True)
            os.makedirs(root, exist_ok=True)
        except Exception as e:
            log.warning(f"Failed to clear request body log directory: {e}")
        return count

    cutoff_ms = int(before_timestamp * 1000)
    deleted = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                ts_ms = int(name.split("_", 1)[0])
            except ValueError:
                continue
            if ts_ms < cutoff_ms:
                try:
                    os.remove(os.path.join(dirpath, name))
                    deleted += 1
                except OSError:
                    pass
    return deleted
