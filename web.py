"""
Main Web Integration - Integrates all routers and modules
"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from log import log

# Import all routers
from src.router.antigravity.openai import router as antigravity_openai_router
from src.router.antigravity.gemini import router as antigravity_gemini_router
from src.router.antigravity.anthropic import router as antigravity_anthropic_router
from src.router.antigravity.model_list import router as antigravity_model_list_router
from src.panel import router as panel_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    log.info("Starting AGYBridge service")

    # Initialize configuration cache
    try:
        import config
        await config.init_config()
        log.info("Configuration cache initialized")
    except Exception as e:
        log.error(f"Configuration cache initialization failed: {e}")

    # Warm up database connection
    try:
        from src.storage.database import get_database
        await get_database()
        log.info("Database connection established")
    except Exception as e:
        log.error(f"Database initialization failed: {e}")

    # Initialize session cache
    try:
        import os as os_module
        from src import session_cache

        redis_url = os_module.getenv("REDIS_URL", "")
        if redis_url:
            await session_cache.init_redis(redis_url)
        else:
            log.info("REDIS_URL not configured, using memory store for session cache")
    except Exception as e:
        log.warning(f"Session cache initialization fallback to memory: {e}")

    # Start per-account background health checker
    try:
        from src.account_health import start_health_check_loop, stop_health_check_loop
        start_health_check_loop()
    except Exception as e:
        log.error(f"Failed to start health check loop: {e}")

    yield

    log.info("Shutting down AGYBridge service")

    try:
        from src.account_health import stop_health_check_loop
        stop_health_check_loop()
    except Exception as e:
        log.debug(f"Error stopping health check loop: {e}")

    try:
        from src.storage.database import close_database
        await close_database()
        log.info("Database connection closed")
    except Exception as e:
        log.error(f"Error closing database: {e}")

    try:
        from src import session_cache
        await session_cache.close()
    except Exception as e:
        log.debug(f"Error closing session cache: {e}")

    log.info("AGYBridge service stopped")


class IPWhitelistMiddleware:
    """
    IP Whitelist ASGI middleware covering panel and API routes.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import config

        try:
            enabled, rules = await config.get_ip_whitelist_rules()
        except Exception as e:
            log.error(f"Failed to read IP whitelist config: {e}")
            await self.app(scope, receive, send)
            return

        if enabled:
            client_ip = (scope.get("client") or (None, None))[0]
            if not client_ip or not config.ip_in_whitelist(client_ip, rules):
                log.warning(f"IP whitelist blocked request: {client_ip} -> {scope.get('path', '')}")
                headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
                accept = headers.get("accept", "")
                response: JSONResponse | PlainTextResponse
                if "application/json" in accept or scope["path"].startswith(("/v1/", "/config/")):
                    response = JSONResponse(
                        status_code=403,
                        content={"error": {"message": "IP not allowed", "code": 403}},
                    )
                else:
                    response = PlainTextResponse("403 Forbidden: IP not allowed", status_code=403)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


class PathPrefixMiddleware:
    """
    Path prefix stripping ASGI middleware for reverse proxies.
    """

    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope["path"] = path[len(self.prefix):] or "/"
                raw_path = scope.get("raw_path")
                if isinstance(raw_path, bytes) and raw_path.startswith(
                    self.prefix.encode("ascii")
                ):
                    scope["raw_path"] = raw_path[len(self.prefix):] or b"/"
        await self.app(scope, receive, send)


app = FastAPI(
    title="AGYBridge",
    description="Antigravity API proxy with OpenAI / Gemini / Claude compatibility",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(IPWhitelistMiddleware)

path_prefix = os.environ.get("PATH_PREFIX", "").rstrip("/")
if path_prefix:
    app.add_middleware(PathPrefixMiddleware, prefix=path_prefix)
    log.info(f"Path prefix stripping enabled: {path_prefix}")

app.include_router(antigravity_openai_router, prefix="", tags=["Antigravity OpenAI API"])
app.include_router(antigravity_gemini_router, prefix="", tags=["Antigravity Gemini API"])
app.include_router(antigravity_model_list_router, prefix="", tags=["Antigravity Model List"])
app.include_router(antigravity_anthropic_router, prefix="", tags=["Antigravity Anthropic Messages"])
app.include_router(panel_router, prefix="", tags=["Panel Interface"])

if os.path.isdir("docs"):
    app.mount("/docs", StaticFiles(directory="docs"), name="docs")


def main():
    """Main startup: run Uvicorn ASGI server."""
    import uvicorn

    port = int(os.environ.get("PORT", 7861))
    host = os.environ.get("HOST", "0.0.0.0")
    workers = int(os.environ.get("WORKERS", 1))

    log.info("=" * 60)
    log.info("Starting AGYBridge")
    log.info("=" * 60)
    log.info(f"Control panel: http://127.0.0.1:{port}")
    if workers > 1:
        log.info(f"Workers: {workers}")
    log.info("=" * 60)

    uvicorn.run(
        "web:app",
        host=host,
        port=port,
        workers=workers if workers > 1 else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
