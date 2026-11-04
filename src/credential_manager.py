"""
Credential Management (Stateless functional encapsulation)
Manages Antigravity credentials using email as unique primary key:
load balancing, automatic token refresh, error tracking, and model-level cooldown.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from log import log

from config import get_credential_select_mode
from src import session_cache
from src.google_oauth_api import Credentials
from src.storage.database import get_database

_sticky_email: Optional[str] = None


def _reset_sticky() -> None:
    """Clear sticky credential pointer (for testing)."""
    global _sticky_email
    _sticky_email = None


async def get_valid_credential(
    model_name: Optional[str] = None,
    session_key: Optional[str] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Acquire available credential according to configured selection mode.
    Skips disabled and cooling credentials.
    Refreshes expired tokens automatically.
    """
    global _sticky_email
    database = await get_database()
    mode = await get_credential_select_mode()

    # cache mode: check session affinity binding first
    if mode == "cache" and session_key:
        bound_email = await session_cache.get_session_binding(session_key)
        if bound_email:
            result = await database.get_available_credential_by_email(
                bound_email, model_name=model_name
            )
            if result:
                log.debug(f"Session cache hit: {bound_email}")
                final = await _validate_or_refresh(result[0], result[1])
                if final is None:
                    await session_cache.delete_session_binding(session_key)
                else:
                    return final
            else:
                await session_cache.delete_session_binding(session_key)

    # sticky mode: prioritize current sticky credential
    if mode == "sticky" and _sticky_email:
        result = await database.get_available_credential_by_email(
            _sticky_email, model_name=model_name
        )
        if result:
            final = await _validate_or_refresh(result[0], result[1])
            if final is not None:
                return final
        _sticky_email = None

    # General random selection (random mode / cache miss / sticky rotation)
    max_retries = 3
    for attempt in range(max_retries):
        result = await database.get_next_available_credential(model_name=model_name)

        if not result:
            if attempt == 0:
                log.warning(f"No available credentials (model_name={model_name})")
            return None

        email, credential_data = result

        if await should_refresh_token(credential_data):
            log.debug(f"Token refresh required: {email}")
            refreshed = await refresh_token(credential_data, email)
            if refreshed:
                await _after_picked(mode, email, session_key)
                return email, refreshed
            log.warning(
                f"Token refresh failed, trying next credential: {email} (attempt={attempt + 1}/{max_retries})"
            )
            continue

        await _after_picked(mode, email, session_key)
        return email, credential_data

    log.error(f"No available credentials after {max_retries} retries (model_name={model_name})")
    return None


async def _validate_or_refresh(
    email: str, credential_data: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Validate token freshness; refresh if needed, return None if permanently expired."""
    if await should_refresh_token(credential_data):
        refreshed = await refresh_token(credential_data, email)
        if refreshed is None:
            return None
        credential_data = refreshed
    return email, credential_data


async def _after_picked(mode: str, email: str, session_key: Optional[str]) -> None:
    """Post-selection hook for session affinity or sticky state update."""
    global _sticky_email
    try:
        if mode == "cache" and session_key:
            await session_cache.set_session_binding(session_key, email)
        elif mode == "sticky":
            _sticky_email = email
    except Exception as e:
        log.debug(f"Failed to record credential affinity: {e}")


async def add_credential(email: str, credential_data: Dict[str, Any]):
    """Add or update credential."""
    database = await get_database()
    await database.store_credential(email, credential_data)
    log.info(f"Credential added/updated: {email}")


async def remove_credential(email: str) -> bool:
    """Delete credential by email."""
    database = await get_database()
    try:
        await database.delete_credential(email)
        log.info(f"Credential removed: {email}")
        return True
    except Exception as e:
        log.error(f"Error removing credential {email}: {e}")
        return False


async def update_credential_state(email: str, state_updates: Dict[str, Any]) -> bool:
    """Update credential fields (disabled/error_codes/tier/project_id)."""
    database = await get_database()
    try:
        success = await database.update_credential_state(email, state_updates)
        if not success:
            log.warning(f"Failed to update credential state: {email}")
        return success
    except Exception as e:
        log.error(f"Error updating credential state {email}: {e}")
        return False


async def set_cred_disabled(email: str, disabled: bool):
    """Enable or disable credential."""
    success = await update_credential_state(email, {"disabled": disabled})
    if success:
        log.info(f"Credential {'disabled' if disabled else 'enabled'}: {email}")
    return success


async def record_api_call_result(
    email: str,
    success: bool,
    error_code: Optional[int] = None,
    cooldown_until: Optional[float] = None,
    model_name: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Record API call result and apply model-level cooldown when needed."""
    database = await get_database()
    try:
        if success:
            asyncio.create_task(database.record_success(email, model_name=model_name))
        elif error_code:
            error_messages = {}
            if error_message:
                error_messages[str(error_code)] = error_message

            await update_credential_state(email, {
                "error_codes": [error_code],
                "error_messages": error_messages,
            })

            if cooldown_until is not None and model_name:
                await database.set_model_cooldown(email, model_name, cooldown_until)
                log.info(
                    f"Setting model-level cooldown: {email}, model={model_name}, "
                    f"until: {datetime.fromtimestamp(cooldown_until, timezone.utc).isoformat()}"
                )
    except Exception as e:
        log.error(f"Error recording API call result for {email}: {e}")


async def should_refresh_token(credential_data: Dict[str, Any]) -> bool:
    """Check if token requires refresh (remaining validity <= 5 minutes)."""
    access_token = credential_data.get("access_token") or credential_data.get("token")
    if not access_token:
        return True

    expiry_str = credential_data.get("expiry")
    if not expiry_str:
        return True

    try:
        if not isinstance(expiry_str, str):
            return True
        if "+" in expiry_str:
            expiry = datetime.fromisoformat(expiry_str)
        elif expiry_str.endswith("Z"):
            expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        else:
            expiry = datetime.fromisoformat(expiry_str)

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        time_left = (expiry - datetime.now(timezone.utc)).total_seconds()
        return time_left <= 300

    except Exception as e:
        log.warning(f"Failed to parse token expiry: {e}, refresh required")
        return True


async def refresh_token(
    credential_data: Dict[str, Any], email: str
) -> Optional[Dict[str, Any]]:
    """Refresh OAuth token and save updated state to database."""
    database = await get_database()
    try:
        creds = Credentials.from_dict(credential_data)

        if not creds.refresh_token:
            log.error(f"Missing refresh_token, cannot refresh: {email}")
            await update_credential_state(email, {"disabled": True})
            log.warning(f"Credential automatically disabled (missing refresh_token): {email}")
            return None

        log.debug(f"Refreshing token for: {email}")
        await creds.refresh()

        if creds.access_token:
            credential_data["access_token"] = creds.access_token
            credential_data["token"] = creds.access_token
        if creds.expires_at:
            credential_data["expiry"] = creds.expires_at.isoformat() if hasattr(creds.expires_at, "isoformat") else str(creds.expires_at)

        await database.store_credential(email, credential_data)
        log.info(f"Token refreshed and persisted: {email}")
        return credential_data

    except Exception as e:
        error_msg = str(e)
        log.error(f"Token refresh failed for {email}: {error_msg}")

        status_code = getattr(e, "status_code", None)

        if _is_permanent_refresh_failure(error_msg, status_code):
            log.warning(f"Permanent credential invalidation detected (HTTP {status_code}): {email}")
            await record_api_call_result(email, False, error_code=status_code or 400)
            if await update_credential_state(email, {"disabled": True}):
                log.warning(f"Permanently invalid credential disabled: {email}")
        else:
            log.warning(f"Temporary token refresh failure (HTTP {status_code}), credential not disabled: {email}")

        return None


def _is_permanent_refresh_failure(error_msg: str, status_code: Optional[int] = None) -> bool:
    """Determine if refresh failure indicates permanent credential invalidation."""
    if status_code is not None:
        if status_code in (400, 401, 403):
            return True
        if status_code in (500, 502, 503, 504):
            return False
        if status_code == 429:
            return False

    permanent_patterns = (
        "invalid_grant",
        "refresh_token_expired",
        "invalid_refresh_token",
        "unauthorized_client",
        "access_denied",
    )
    error_msg_lower = error_msg.lower()
    return any(p in error_msg_lower for p in permanent_patterns)
