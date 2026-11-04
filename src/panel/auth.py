"""
Authentication Route Module - Handles /auth/* HTTP requests
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from log import log
from src.auth import (
    asyncio_complete_auth_flow,
    complete_auth_flow_from_callback_url,
    create_auth_url,
    get_auth_status,
    verify_password,
)
from src.models import (
    LoginRequest,
    AuthStartRequest,
    AuthCallbackRequest,
    AuthCallbackUrlRequest,
)
from src.utils import verify_panel_token


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(request: LoginRequest):
    """User login endpoint returning password as panel token."""
    try:
        if await verify_password(request.password):
            return JSONResponse(content={"token": request.password, "message": "Berhasil masuk"})
        else:
            raise HTTPException(status_code=401, detail="Kata sandi salah")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal masuk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_auth(request: AuthStartRequest, token: str = Depends(verify_panel_token)):
    """Start OAuth authorization flow with automatic project ID detection."""
    try:
        project_id = request.project_id
        if not project_id:
            log.info("Project ID tidak disediakan, menggunakan deteksi otomatis...")

        user_session = token if token else None
        result = await create_auth_url(project_id, user_session)

        if result["success"]:
            return JSONResponse(
                content={
                    "auth_url": result["auth_url"],
                    "state": result["state"],
                    "auto_project_detection": result.get("auto_project_detection", False),
                    "detected_project_id": result.get("detected_project_id"),
                }
            )
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal memulai alur autentikasi: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/callback")
async def auth_callback(request: AuthCallbackRequest, token: str = Depends(verify_panel_token)):
    """Handle OAuth callback completion."""
    try:
        project_id = request.project_id
        user_session = token if token else None
        result = await asyncio_complete_auth_flow(project_id, user_session)

        if result["success"]:
            return JSONResponse(
                content={
                    "credentials": result["credentials"],
                    "email": result.get("email", ""),
                    "tier": result.get("tier"),
                    "message": "Autentikasi berhasil, kredensial telah disimpan",
                    "auto_detected_project": result.get("auto_detected_project", False),
                }
            )
        else:
            if result.get("requires_manual_project_id"):
                return JSONResponse(
                    status_code=400,
                    content={"error": result["error"], "requires_manual_project_id": True},
                )
            elif result.get("requires_project_selection"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": result["error"],
                        "requires_project_selection": True,
                        "available_projects": result["available_projects"],
                    },
                )
            else:
                raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal memproses callback autentikasi: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/callback-url")
async def auth_callback_url(request: AuthCallbackUrlRequest, token: str = Depends(verify_panel_token)):
    """Complete authorization flow directly from pasted callback URL."""
    try:
        if not request.callback_url or not request.callback_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Mohon masukkan URL callback yang valid")

        result = await complete_auth_flow_from_callback_url(
            request.callback_url, request.project_id
        )

        if result["success"]:
            return JSONResponse(
                content={
                    "credentials": result["credentials"],
                    "email": result.get("email", ""),
                    "tier": result.get("tier"),
                    "message": "Autentikasi callback URL berhasil, kredensial telah disimpan",
                    "auto_detected_project": result.get("auto_detected_project", False),
                }
            )
        else:
            if result.get("requires_manual_project_id"):
                return JSONResponse(
                    status_code=400,
                    content={"error": result["error"], "requires_manual_project_id": True},
                )
            elif result.get("requires_project_selection"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": result["error"],
                        "requires_project_selection": True,
                        "available_projects": result["available_projects"],
                    },
                )
            else:
                raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal memproses autentikasi dari callback URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{project_id}")
async def check_auth_status(project_id: str, token: str = Depends(verify_panel_token)):
    """Check authorization progress status."""
    try:
        if not project_id:
            raise HTTPException(status_code=400, detail="Project ID tidak boleh kosong")

        status = get_auth_status(project_id)
        return JSONResponse(content=status)

    except Exception as e:
        log.error(f"Gagal memeriksa status autentikasi: {e}")
        raise HTTPException(status_code=500, detail=str(e))
