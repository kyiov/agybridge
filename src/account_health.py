"""
Account Health Check & Session Liveness Module
Proactively detects silently expired or hung Google OAuth sessions,
marks hung/unhealthy credentials, and prevents requests from hanging.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx
from config import (
    get_health_check_enabled,
    get_health_check_interval,
    get_health_check_timeout,
)
from log import log
from src.google_oauth_api import Credentials
from src.storage.database import get_database

_health_check_task: Optional[asyncio.Task] = None


async def mark_credential_hung(email: str, reason: str = "Request timed out (silent session drop)") -> None:
    """
    Mark an account as hung and apply temporary cooldown.
    Called when an active request times out on an account.
    """
    database = await get_database()
    current_time = time.time()
    # 5 minute cooldown for hung session to avoid hitting it again
    cooldown_until = current_time + 300

    log.warning(f"[HEALTH CHECK] Marking credential as HUNG: {email} - {reason}")
    try:
        await database.update_credential_state(email, {
            "health_status": "hung",
            "health_check_error": reason[:500],
            "last_health_check": current_time,
        })
        # Set cooldown for all main model families
        for group in ("gemini", "argon", "claude"):
            await database.set_model_cooldown(email, group, cooldown_until)
    except Exception as e:
        log.error(f"[HEALTH CHECK] Failed to mark credential {email} as hung: {e}")


async def check_credential_health(
    email: str,
    credential_data: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Probe an individual account's session health and liveness.
    1. Checks token freshness and refresh capability.
    2. Sends a strict-timeout quota summary probe to Antigravity endpoint.
    """
    database = await get_database()
    if timeout is None:
        timeout = await get_health_check_timeout()

    if credential_data is None:
        credential_data = await database.get_credential(email)

    if not credential_data:
        return {"email": email, "healthy": False, "status": "not_found", "error": "Credential not found"}

    refresh_token = credential_data.get("refresh_token")
    if not refresh_token:
        await database.update_credential_state(email, {
            "health_status": "unhealthy",
            "health_check_error": "Missing refresh_token",
            "last_health_check": time.time(),
        })
        return {"email": email, "healthy": False, "status": "missing_refresh_token", "error": "Missing refresh_token"}

    # Validate / refresh token if expired
    from src.credential_manager import refresh_token as do_refresh_token, should_refresh_token

    if await should_refresh_token(credential_data):
        log.debug(f"[HEALTH CHECK] Refreshing token for {email} prior to probe...")
        try:
            refreshed = await asyncio.wait_for(
                do_refresh_token(credential_data, email),
                timeout=timeout,
            )
            if not refreshed:
                await database.update_credential_state(email, {
                    "health_status": "expired",
                    "health_check_error": "Token refresh failed (session expired)",
                    "last_health_check": time.time(),
                })
                return {"email": email, "healthy": False, "status": "expired", "error": "Token refresh failed"}
            credential_data = refreshed
        except asyncio.TimeoutError:
            await mark_credential_hung(email, "Token refresh timed out")
            return {"email": email, "healthy": False, "status": "hung", "error": "Token refresh timed out"}
        except Exception as e:
            await database.update_credential_state(email, {
                "health_status": "unhealthy",
                "health_check_error": f"Token refresh error: {e}",
                "last_health_check": time.time(),
            })
            return {"email": email, "healthy": False, "status": "unhealthy", "error": str(e)}

    access_token = credential_data.get("access_token") or credential_data.get("token")
    project_id = credential_data.get("project_id", "")
    if not access_token:
        return {"email": email, "healthy": False, "status": "no_token", "error": "No access token"}

    # Probe upstream session liveness via retrieveUserQuotaSummary
    from src.api.antigravity import fetch_quota_info

    try:
        quota_result = await asyncio.wait_for(
            fetch_quota_info(access_token, project_id),
            timeout=timeout,
        )

        if quota_result.get("success"):
            tier = quota_result.get("accountTier", "pro")
            await database.update_credential_state(email, {
                "health_status": "healthy",
                "health_check_error": None,
                "last_health_check": time.time(),
                "tier": tier,
            })
            log.debug(f"[HEALTH CHECK] Account healthy: {email} (tier={tier})")
            return {
                "email": email,
                "healthy": True,
                "status": "healthy",
                "tier": tier,
            }
        else:
            err = str(quota_result.get("error", "Unknown error"))
            log.warning(f"[HEALTH CHECK] Account unhealthy: {email} - {err}")
            status = "expired" if "401" in err or "403" in err else "unhealthy"
            await database.update_credential_state(email, {
                "health_status": status,
                "health_check_error": err[:500],
                "last_health_check": time.time(),
            })
            return {
                "email": email,
                "healthy": False,
                "status": status,
                "error": err,
            }

    except asyncio.TimeoutError:
        await mark_credential_hung(email, f"Quota summary probe timed out after {timeout}s")
        return {
            "email": email,
            "healthy": False,
            "status": "hung",
            "error": f"Session probe timed out after {timeout}s",
        }
    except Exception as e:
        log.warning(f"[HEALTH CHECK] Session check exception for {email}: {e}")
        await database.update_credential_state(email, {
            "health_status": "unhealthy",
            "health_check_error": str(e)[:500],
            "last_health_check": time.time(),
        })
        return {
            "email": email,
            "healthy": False,
            "status": "unhealthy",
            "error": str(e),
        }


async def check_all_credentials_health(concurrency: int = 5) -> Dict[str, Any]:
    """
    Check health of all enabled credentials concurrently.
    """
    database = await get_database()
    emails = await database.list_credentials()
    if not emails:
        return {"total": 0, "healthy": 0, "hung": 0, "unhealthy": 0, "results": []}

    sem = asyncio.Semaphore(concurrency)

    async def _bound_check(email: str):
        async with sem:
            state = await database.get_credential_state(email)
            if state.get("disabled", False):
                return {"email": email, "healthy": False, "status": "disabled", "error": "Credential disabled"}
            return await check_credential_health(email)

    results = await asyncio.gather(*[_bound_check(e) for e in emails], return_exceptions=True)

    formatted_results: List[Dict[str, Any]] = []
    healthy_count = 0
    hung_count = 0
    unhealthy_count = 0

    for res in results:
        if isinstance(res, Exception):
            formatted_results.append({"healthy": False, "status": "error", "error": str(res)})
            unhealthy_count += 1
        elif isinstance(res, dict):
            formatted_results.append(res)
            status = res.get("status")
            if status == "healthy":
                healthy_count += 1
            elif status == "hung":
                hung_count += 1
            elif status not in ("disabled",):
                unhealthy_count += 1

    log.info(
        f"[HEALTH CHECK] Completed check for {len(emails)} credentials: "
        f"{healthy_count} healthy, {hung_count} hung, {unhealthy_count} unhealthy"
    )

    return {
        "total": len(emails),
        "healthy": healthy_count,
        "hung": hung_count,
        "unhealthy": unhealthy_count,
        "results": formatted_results,
    }


# ====================== Background Task ======================

async def _health_check_worker() -> None:
    """Periodic background health checker task."""
    # Delay initial check slightly so the server completes startup
    await asyncio.sleep(5)

    while True:
        try:
            if await get_health_check_enabled():
                log.debug("[HEALTH CHECK] Starting periodic credential health check...")
                await check_all_credentials_health()
        except asyncio.CancelledError:
            log.info("[HEALTH CHECK] Background worker cancelled")
            break
        except Exception as e:
            log.error(f"[HEALTH CHECK] Periodic health check error: {e}")

        try:
            interval = await get_health_check_interval()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break


def start_health_check_loop() -> None:
    """Start background health check loop."""
    global _health_check_task
    if _health_check_task is None or _health_check_task.done():
        _health_check_task = asyncio.create_task(_health_check_worker())
        log.info("[HEALTH CHECK] Background health check worker started")


def stop_health_check_loop() -> None:
    """Stop background health check loop."""
    global _health_check_task
    if _health_check_task and not _health_check_task.done():
        _health_check_task.cancel()
        _health_check_task = None
        log.info("[HEALTH CHECK] Background health check worker stopped")
