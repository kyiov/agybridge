"""
Usage Logs Route Module - Handles /usage-logs/* HTTP requests
Queries usage_log table: paginated lists, aggregate metrics, clearing, and payload inspection
"""

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from config import get_usage_log_enabled
from log import log
from src.request_body_log import clear_request_body_logs, read_request_body_log
from src.storage.database import UsageLog, get_database
from src.usage_log import clear_usage_logs
from src.utils import verify_panel_token


router = APIRouter(prefix="/usage-logs", tags=["usage-logs"])


@router.get("/list")
async def get_usage_logs(
    token: str = Depends(verify_panel_token),
    offset: int = 0,
    limit: int = 50,
    start_timestamp: Optional[float] = None,
    end_timestamp: Optional[float] = None,
    model_name: str = "",
    credential_email: str = "",
    api_format: str = "",
    status: str = "all",
    is_stream: Optional[bool] = None,
    status_code: Optional[int] = None,
):
    """Paginated query of usage logs (ordered newest to oldest)."""
    try:
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit harus antara 1-1000")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset tidak boleh negatif")

        database = await get_database()
        items, total = await database.query_usage_logs(
            offset=offset,
            limit=limit,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            model_name=model_name.strip(),
            credential_email=credential_email.strip(),
            api_format=api_format.strip(),
            status=status,
            is_stream=is_stream,
            status_code=status_code,
        )
        return JSONResponse(content={"items": items, "total": total})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to query usage logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_usage_stats(
    token: str = Depends(verify_panel_token),
    start_timestamp: Optional[float] = None,
    end_timestamp: Optional[float] = None,
):
    """Aggregate statistics: total requests, success/failure rate, token usage, latency."""
    try:
        database = await get_database()
        stats = await database.get_usage_stats(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        return JSONResponse(content=stats)
    except Exception as e:
        log.error(f"Failed to query usage stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear")
async def clear_logs(
    token: str = Depends(verify_panel_token),
    days: int = 30,
):
    """Clean logs older than N days and return deleted count."""
    try:
        if days < 0:
            raise HTTPException(status_code=400, detail="Jumlah hari tidak boleh bernilai negatif")
        if days == 0:
            deleted = await clear_usage_logs(0)
            files_deleted = await asyncio.to_thread(clear_request_body_logs)
            return JSONResponse(content={
                "message": "Seluruh log berhasil dibersihkan",
                "deleted": deleted,
                "files_deleted": files_deleted,
            })
        deleted = await clear_usage_logs(days)
        files_deleted = await asyncio.to_thread(
            clear_request_body_logs, time.time() - days * 86400
        )
        return JSONResponse(content={
            "message": f"Log sebelum {days} hari yang lalu berhasil dibersihkan",
            "deleted": deleted,
            "files_deleted": files_deleted,
        })
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal membersihkan log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/truncate")
async def truncate_logs(token: str = Depends(verify_panel_token)):
    """Truncate logs by dropping and re-creating the table."""
    try:
        database = await get_database()
        _, total = await database.query_usage_logs(offset=0, limit=1)

        async with database.session() as s:
            await s.execute(text(f"DROP TABLE IF EXISTS {UsageLog.__tablename__}"))

        async with database._engine.begin() as conn:
            await conn.run_sync(database._create_tables)

        files_deleted = await asyncio.to_thread(clear_request_body_logs)

        return JSONResponse(content={
            "message": "Seluruh log berhasil dihapus (tabel diinisialisasi ulang)",
            "deleted": total,
            "files_deleted": files_deleted,
        })
    except Exception as e:
        log.error(f"Gagal mengosongkan log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/request-body")
async def get_request_body_log(
    path: str,
    token: str = Depends(verify_panel_token),
):
    """Read request payload JSON log from disk by file index path."""
    try:
        data = await asyncio.to_thread(read_request_body_log, path)
        if data is None:
            raise HTTPException(status_code=404, detail="Berkas log detail tidak ditemukan atau telah dibersihkan")
        return JSONResponse(content=data)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal membaca log payload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_usage_log_config(token: str = Depends(verify_panel_token)):
    """Get logging configuration status."""
    return JSONResponse(content={
        "enabled": await get_usage_log_enabled(),
    })
