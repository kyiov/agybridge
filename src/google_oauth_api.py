"""
Google OAuth2 Authentication Module
"""

import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import jwt

from config import (
    get_googleapis_proxy_url,
    get_oauth_proxy_url,
)
from log import log

from src.httpx_client import get_async, post_async


class TokenError(Exception):
    """Token-related exceptions."""
    pass


class Credentials:
    """OAuth Credentials container and refresh controller."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str = None,
        client_id: str = None,
        client_secret: str = None,
        expires_at: datetime = None,
        project_id: str = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.expires_at = expires_at
        self.project_id = project_id

        self.oauth_base_url = None
        self.token_endpoint = None

    def is_expired(self) -> bool:
        """Check whether token is expired with 3-minute grace buffer."""
        if not self.expires_at:
            return True

        buffer = timedelta(minutes=3)
        return (self.expires_at - buffer) <= datetime.now(timezone.utc)

    async def refresh_if_needed(self) -> bool:
        """Refresh token if currently expired."""
        if not self.is_expired():
            return False

        if not self.refresh_token:
            raise TokenError("Refresh token required but not provided")

        await self.refresh()
        return True

    async def refresh(self):
        """Execute OAuth token refresh via token endpoint."""
        if not self.refresh_token:
            raise TokenError("No refresh token available")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            oauth_base_url = await get_oauth_proxy_url()
            token_url = f"{oauth_base_url.rstrip('/')}/token"
            response = await post_async(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data["access_token"]

            if "expires_in" in token_data:
                expires_in = int(token_data["expires_in"])
                current_utc = datetime.now(timezone.utc)
                self.expires_at = current_utc + timedelta(seconds=expires_in)
                log.debug(
                    f"Token refresh: current_utc={current_utc.isoformat()}, "
                    f"expires_in={expires_in}s, "
                    f"expires_at={self.expires_at.isoformat()}"
                )

            if "refresh_token" in token_data:
                self.refresh_token = token_data["refresh_token"]

            log.debug(f"Token refreshed successfully, expires_at: {self.expires_at}")

        except Exception as e:
            error_msg = str(e)
            status_code = None
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                status_code = e.response.status_code
                error_msg = f"Token refresh failed (HTTP {status_code}): {error_msg}"
            else:
                error_msg = f"Token refresh failed: {error_msg}"

            log.error(error_msg)
            token_error = TokenError(error_msg)
            token_error.status_code = status_code
            raise token_error

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Credentials":
        """Instantiate Credentials from dictionary."""
        expires_at = None
        if "expiry" in data and data["expiry"]:
            try:
                expiry_str = data["expiry"]
                if isinstance(expiry_str, str):
                    if expiry_str.endswith("Z"):
                        expires_at = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                    elif "+" in expiry_str:
                        expires_at = datetime.fromisoformat(expiry_str)
                    else:
                        expires_at = datetime.fromisoformat(expiry_str).replace(tzinfo=timezone.utc)
            except ValueError:
                log.warning(f"Unable to parse expiry string: {expiry_str}")

        return cls(
            access_token=data.get("token") or data.get("access_token", ""),
            refresh_token=data.get("refresh_token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            expires_at=expires_at,
            project_id=data.get("project_id"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize credentials to dictionary."""
        result = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "project_id": self.project_id,
        }

        if self.expires_at:
            result["expiry"] = self.expires_at.isoformat()

        return result


class Flow:
    """OAuth Authorization Code Flow controller."""

    def __init__(
        self, client_id: str, client_secret: str, scopes: List[str], redirect_uri: str = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.redirect_uri = redirect_uri

        self.oauth_base_url = None
        self.token_endpoint = None
        self.auth_endpoint = "https://accounts.google.com/o/oauth2/auth"

        self.credentials: Optional[Credentials] = None

    def get_auth_url(self, state: str = None, **kwargs) -> str:
        """Generate browser authorization redirect URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }

        if state:
            params["state"] = state

        params.update(kwargs)
        return f"{self.auth_endpoint}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> Credentials:
        """Exchange authorization code for token pair."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
        }

        try:
            oauth_base_url = await get_oauth_proxy_url()
            token_url = f"{oauth_base_url.rstrip('/')}/token"
            response = await post_async(
                token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()

            token_data = response.json()

            expires_at = None
            if "expires_in" in token_data:
                expires_in = int(token_data["expires_in"])
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            self.credentials = Credentials(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                client_id=self.client_id,
                client_secret=self.client_secret,
                expires_at=expires_at,
            )

            return self.credentials

        except Exception as e:
            error_msg = f"Failed to acquire token: {str(e)}"
            log.error(error_msg)
            raise TokenError(error_msg)


class ServiceAccount:
    """Service Account JWT-bearer authentication handler."""

    def __init__(
        self, email: str, private_key: str, project_id: str = None, scopes: List[str] = None
    ):
        self.email = email
        self.private_key = private_key
        self.project_id = project_id
        self.scopes = scopes or []

        self.oauth_base_url = None
        self.token_endpoint = None

        self.access_token: Optional[str] = None
        self.expires_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        if not self.expires_at:
            return True

        buffer = timedelta(minutes=3)
        return (self.expires_at - buffer) <= datetime.now(timezone.utc)

    def create_jwt(self) -> str:
        now = int(time.time())

        payload = {
            "iss": self.email,
            "scope": " ".join(self.scopes) if self.scopes else "",
            "aud": self.token_endpoint,
            "exp": now + 3600,
            "iat": now,
        }

        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def get_access_token(self) -> str:
        if not self.is_expired() and self.access_token:
            return self.access_token

        assertion = self.create_jwt()
        data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}

        try:
            oauth_base_url = await get_oauth_proxy_url()
            token_url = f"{oauth_base_url.rstrip('/')}/token"
            response = await post_async(
                token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data["access_token"]

            if "expires_in" in token_data:
                expires_in = int(token_data["expires_in"])
                self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return self.access_token

        except Exception as e:
            error_msg = f"Service Account failed to acquire token: {str(e)}"
            log.error(error_msg)
            raise TokenError(error_msg)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], scopes: List[str] = None) -> "ServiceAccount":
        return cls(
            email=data["client_email"],
            private_key=data["private_key"],
            project_id=data.get("project_id"),
            scopes=scopes,
        )


async def get_user_info(credentials: Credentials) -> Optional[Dict[str, Any]]:
    """Retrieve Google userinfo profile."""
    await credentials.refresh_if_needed()

    try:
        googleapis_base_url = await get_googleapis_proxy_url()
        userinfo_url = f"{googleapis_base_url.rstrip('/')}/oauth2/v2/userinfo"
        response = await get_async(
            userinfo_url, headers={"Authorization": f"Bearer {credentials.access_token}"}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"Failed to fetch userinfo: {e}")
        return None


async def get_user_email(credentials: Credentials) -> Optional[str]:
    """Retrieve user email address from userinfo."""
    try:
        await credentials.refresh_if_needed()
        user_info = await get_user_info(credentials)
        if user_info:
            email = user_info.get("email")
            if email:
                log.info(f"Retrieved email address: {email}")
                return email
            else:
                log.warning(f"No email found in userinfo response: {user_info}")
                return None
        else:
            log.warning("Failed to fetch userinfo")
            return None

    except Exception as e:
        log.error(f"Failed to retrieve user email: {e}")
        return None


async def fetch_user_email_from_file(cred_data: Dict[str, Any]) -> Optional[str]:
    """Extract user email address from raw credential dictionary."""
    try:
        credentials = Credentials.from_dict(cred_data)
        if not credentials or not credentials.access_token:
            log.warning("Unable to initialize credentials or acquire access token from data")
            return None

        return await get_user_email(credentials)

    except Exception as e:
        log.error(f"Failed to extract user email: {e}")
        return None


async def validate_token(token: str) -> Optional[Dict[str, Any]]:
    """Validate access token via tokeninfo endpoint."""
    try:
        oauth_base_url = await get_oauth_proxy_url()
        tokeninfo_url = f"{oauth_base_url.rstrip('/')}/tokeninfo?access_token={token}"

        response = await get_async(tokeninfo_url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"Failed to validate token: {e}")
        return None


async def fetch_project_id_and_tier(
    access_token: str,
    user_agent: str,
    api_base_url: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch project_id and subscription tier from upstream API.
    Returns (project_id, subscription_tier).
    """
    headers = {
        'User-Agent': user_agent,
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept-Encoding': 'gzip'
    }

    def _map_raw_tier(raw_tier: Optional[str]) -> Optional[str]:
        if not raw_tier:
            return None

        lowered = raw_tier.lower()
        if "ultra" in lowered:
            return "ultra"
        if "pro" in lowered:
            return "pro"
        if "free" in lowered:
            return "free"

        return "free"

    subscription_tier = None

    try:
        project_id, raw_tier = await _try_load_code_assist(api_base_url, headers)
        subscription_tier = _map_raw_tier(raw_tier)

        if raw_tier:
            log.info(
                f"[fetch_project_id_and_tier] Raw tier '{raw_tier}' mapped to '{subscription_tier}'"
            )

        if project_id:
            return project_id, subscription_tier

        log.warning("[fetch_project_id_and_tier] loadCodeAssist did not return project_id")

    except Exception as e:
        log.warning(f"[fetch_project_id_and_tier] loadCodeAssist failed: {type(e).__name__}: {e}")

    log.warning("[fetch_project_id_and_tier] Using fallback project_id: aicode-consumers")
    return "aicode-consumers", subscription_tier


async def _try_load_code_assist(
    api_base_url: str,
    headers: dict
) -> Tuple[Optional[str], Optional[str]]:
    """
    Execute loadCodeAssist call to discover project_id and subscription tier.
    """
    request_url = f"{api_base_url.rstrip('/')}/v1internal:loadCodeAssist"
    request_body = {
        "metadata": {
            "ideType": "ANTIGRAVITY"
        }
    }

    log.debug(f"[loadCodeAssist] Fetching project_id from: {request_url}")
    log.debug(f"[loadCodeAssist] Request body: {request_body}")

    response = await post_async(
        request_url,
        json=request_body,
        headers=headers,
        timeout=30.0,
    )

    log.debug(f"[loadCodeAssist] Response status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        paid_tier = data.get("paidTier", {})
        current_tier = data.get("currentTier", {})

        subscription_tier = None
        if isinstance(paid_tier, dict) and paid_tier.get("id"):
            subscription_tier = paid_tier.get("id")
            log.info(f"[loadCodeAssist] Found paidTier: {subscription_tier}")
        elif isinstance(current_tier, dict) and current_tier.get("id"):
            subscription_tier = current_tier.get("id")
            log.info(f"[loadCodeAssist] Found currentTier: {subscription_tier}")

        if current_tier:
            log.info("[loadCodeAssist] User is already activated")

            project_id = data.get("cloudaicompanionProject")
            if project_id:
                log.info(f"[loadCodeAssist] Successfully fetched project_id: {project_id}, tier: {subscription_tier}")
                return project_id, subscription_tier

            log.warning("[loadCodeAssist] No project_id in response")
            return None, subscription_tier
        else:
            log.info("[loadCodeAssist] User not activated yet (no currentTier)")
            return None, None
    else:
        log.warning(f"[loadCodeAssist] Failed: HTTP {response.status_code}")
        raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
