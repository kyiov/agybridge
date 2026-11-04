"""
Shared API Client Utilities: auto-ban, error retries, call result tracking, cooldown parsing
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import (
    get_auto_ban_enabled,
    get_auto_ban_error_codes,
    get_retry_429_enabled,
    get_retry_429_interval,
    get_retry_429_max_retries,
)
from log import log
from src.credential_manager import record_api_call_result, set_cred_disabled


async def check_should_auto_ban(status_code: int) -> bool:
    """Check if error status code should trigger auto-ban for the credential."""
    return (
        await get_auto_ban_enabled()
        and status_code in await get_auto_ban_error_codes()
    )


async def handle_auto_ban(status_code: int, email: str) -> None:
    """Execute auto-ban by disabling credential."""
    if email:
        log.warning(f"[AUTO_BAN] Status {status_code} triggers auto-ban for credential: {email}")
        await set_cred_disabled(email, True)


async def handle_error_with_retry(
    status_code: int,
    email: str,
    retry_enabled: bool,
    attempt: int,
    max_retries: int,
    retry_interval: float,
) -> bool:
    """
    Handle errors and evaluate retry policy.
    Retries apply to 429, 500, 503, and auto-banned credentials.
    """
    if await check_should_auto_ban(status_code):
        await handle_auto_ban(status_code, email)

        if retry_enabled and attempt < max_retries:
            log.info(
                f"[RETRY] Retrying with next credential after auto-ban "
                f"(status {status_code}, attempt {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(retry_interval)
            return True
        return False

    if status_code in (429, 500, 503) and retry_enabled and attempt < max_retries:
        log.info(
            f"[RETRY] {status_code} error encountered, retrying "
            f"(attempt {attempt + 1}/{max_retries})"
        )
        await asyncio.sleep(retry_interval)
        return True

    return False


async def get_retry_config() -> Dict[str, Any]:
    """Retrieve rate limiting retry configuration."""
    return {
        "retry_enabled": await get_retry_429_enabled(),
        "max_retries": await get_retry_429_max_retries(),
        "retry_interval": await get_retry_429_interval(),
    }


async def record_api_call_success(
    email: str,
    model_name: Optional[str] = None,
) -> None:
    """Record successful API call."""
    if email:
        await record_api_call_result(
            email, True, model_name=model_name
        )


async def record_api_call_error(
    email: str,
    status_code: int,
    cooldown_until: Optional[float] = None,
    model_name: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Record failed API call."""
    if email:
        await record_api_call_result(
            email,
            False,
            status_code,
            cooldown_until=cooldown_until,
            model_name=model_name,
            error_message=error_message,
        )


async def parse_and_log_cooldown(error_text: str) -> Optional[float]:
    """Parse and log rate limit cooldown timestamp."""
    try:
        error_data = json.loads(error_text)
        cooldown_until = parse_quota_reset_timestamp(error_data)
        if cooldown_until:
            log.info(
                f"Rate limit cooldown detected until: "
                f"{datetime.fromtimestamp(cooldown_until, timezone.utc).isoformat()}"
            )
            return cooldown_until
    except Exception as parse_err:
        log.debug(f"Failed to parse cooldown time: {parse_err}")
    return None


def parse_quota_reset_timestamp(error_response: dict) -> Optional[float]:
    """
    Extract quota reset timestamp from Antigravity 429 response.
    Priority:
    1. ErrorInfo.metadata.quotaResetTimeStamp (absolute timestamp)
    2. ErrorInfo.metadata.quotaResetDelay (duration string)
    3. RetryInfo.retryDelay (duration seconds)
    """
    try:
        error_obj = error_response.get("error", {})
        details = error_obj.get("details", [])

        error_info_metadata: Optional[dict] = None
        retry_delay_str: Optional[str] = None

        for detail in details:
            detail_type = detail.get("@type", "")
            if detail_type == "type.googleapis.com/google.rpc.ErrorInfo":
                error_info_metadata = detail.get("metadata", {})
            elif detail_type == "type.googleapis.com/google.rpc.RetryInfo":
                retry_delay_str = detail.get("retryDelay")

        unit_to_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}

        if error_info_metadata:
            reset_timestamp_str = error_info_metadata.get("quotaResetTimeStamp")
            if reset_timestamp_str:
                if reset_timestamp_str.endswith("Z"):
                    reset_timestamp_str = reset_timestamp_str.replace("Z", "+00:00")

                reset_dt = datetime.fromisoformat(reset_timestamp_str)
                if reset_dt.tzinfo is None:
                    reset_dt = reset_dt.replace(tzinfo=timezone.utc)

                return reset_dt.astimezone(timezone.utc).timestamp()

        if error_info_metadata:
            reset_delay_str = error_info_metadata.get("quotaResetDelay")
            if reset_delay_str:
                parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", reset_delay_str)
                if parts:
                    cooldown_seconds = sum(
                        float(value) * unit_to_seconds[unit] for value, unit in parts
                    )
                    if cooldown_seconds > 0:
                        return time.time() + cooldown_seconds

        if retry_delay_str:
            parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", retry_delay_str)
            if parts:
                cooldown_seconds = sum(
                    float(value) * unit_to_seconds[unit] for value, unit in parts
                )
                if cooldown_seconds > 0:
                    return time.time() + cooldown_seconds

        return None

    except Exception:
        return None
