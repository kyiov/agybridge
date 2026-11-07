import os
from typing import Optional

import httpx

from config import get_api_password, get_panel_password
from fastapi import Depends, HTTPException, Header, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from log import log

# HTTP Bearer security scheme
security = HTTPBearer()

# ====================== OAuth Configuration ======================

_DEFAULT_ANTIGRAVITY_CLI_VERSION = "1.5.2"


def _get_latest_antigravity_cli_version() -> str:
    """Retrieve Antigravity CLI version string (pinned to 1.5.2, configurable via ANTIGRAVITY_CLI_VERSION)."""
    env_version = os.getenv("ANTIGRAVITY_CLI_VERSION", "").strip()
    if env_version:
        return env_version.lstrip("vV")
    return _DEFAULT_ANTIGRAVITY_CLI_VERSION


ANTIGRAVITY_CLI_VERSION = _get_latest_antigravity_cli_version()
ANTIGRAVITY_CLI_PLATFORM = "windows/amd64"
ANTIGRAVITY_USER_AGENT = f"antigravity/cli/{ANTIGRAVITY_CLI_VERSION} {ANTIGRAVITY_CLI_PLATFORM}"
log.info(f"Antigravity CLI version: {ANTIGRAVITY_CLI_VERSION}")

# Antigravity OAuth Configuration
_DEFAULT_CLIENT_ID = bytes.fromhex(
    "313037313030363036303539312d746d687373696e326832316c63726532333576746f6c6f6a68346734303365702e617070732e676f6f676c6575736572636f6e74656e742e636f6d"
).decode("utf-8")
_DEFAULT_CLIENT_SECRET = bytes.fromhex(
    "474f435350582d4b35384657523438364c644c4a316d4c4238735843347a3671444166"
).decode("utf-8")

ANTIGRAVITY_CLIENT_ID = os.getenv("ANTIGRAVITY_CLIENT_ID", _DEFAULT_CLIENT_ID)
ANTIGRAVITY_CLIENT_SECRET = os.getenv("ANTIGRAVITY_CLIENT_SECRET", _DEFAULT_CLIENT_SECRET)
ANTIGRAVITY_SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/cclog',
    'https://www.googleapis.com/auth/experimentsandconfigs'
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALLBACK_HOST = "localhost"

# ====================== Model Helper Functions ======================

_ANTI_TRUNCATION_PREFIXES = ("anti-truncate-", "notrunc-")


def is_anti_truncation_model(model_name: str) -> bool:
    """Check if model name indicates anti-truncation should be used."""
    return any(model_name.startswith(p) for p in _ANTI_TRUNCATION_PREFIXES)


def get_base_model_from_feature_model(model_name: str) -> str:
    """Get base model name from feature model name."""
    for prefix in _ANTI_TRUNCATION_PREFIXES:
        if model_name.startswith(prefix):
            return model_name[len(prefix):]
    return model_name


# ====================== Authentication Functions ======================

async def authenticate_flexible(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    access_token: Optional[str] = Header(None, alias="access_token"),
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    x_anthropic_auth_token: Optional[str] = Header(None, alias="x-anthropic-auth-token"),
    anthropic_auth_token: Optional[str] = Header(None, alias="anthropic-auth-token"),
    key: Optional[str] = Query(None)
) -> str:
    """
    Flexible multi-standard authentication resolver.
    Supports OpenAI Bearer, Google x-goog-api-key/key query param, Anthropic tokens, and x-api-key.
    """
    password = await get_api_password()
    token = None
    auth_method = None

    if key:
        token = key
        auth_method = "URL parameter 'key'"
    elif x_goog_api_key:
        token = x_goog_api_key
        auth_method = "x-goog-api-key header"
    elif x_anthropic_auth_token:
        token = x_anthropic_auth_token
        auth_method = "x-anthropic-auth-token header"
    elif anthropic_auth_token:
        token = anthropic_auth_token
        auth_method = "anthropic-auth-token header"
    elif x_api_key:
        token = x_api_key
        auth_method = "x-api-key header"
    elif access_token:
        token = access_token
        auth_method = "access_token header"
    elif authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme. Use 'Bearer <token>'",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization[7:]
        auth_method = "Authorization Bearer header"

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials. Use 'key' URL parameter, 'x-goog-api-key', 'x-anthropic-auth-token', 'anthropic-auth-token', 'x-api-key', 'access_token' header, or 'Authorization: Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if token != password:
        log.debug(f"Authentication failed using {auth_method}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kata sandi API salah"
        )
    
    log.debug(f"Authentication successful using {auth_method}")
    return token


authenticate_bearer = authenticate_flexible
authenticate_gemini_flexible = authenticate_flexible


# ====================== Panel Authentication Functions ======================

async def verify_panel_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify Bearer token against configured panel password."""
    password = await get_panel_password()
    if credentials.credentials != password:
        raise HTTPException(status_code=401, detail="Kata sandi salah")
    return credentials.credentials
