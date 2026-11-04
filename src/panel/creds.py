"""
Credential Management Route Module - Handles /creds/* HTTP requests
Credentials use email as unique primary key. Import/export JSON format:
  { "refresh_token": "...", "email": "...", "tier": "...", "project_id": "..." }
"""

import asyncio
import io
import json
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Response
from fastapi.responses import JSONResponse

from log import log
from src.credential_manager import (
    add_credential,
    remove_credential,
    set_cred_disabled,
)
from src.models import (
    CredFileActionRequest,
    CredFileBatchActionRequest
)
from src.storage.database import get_database
from src.utils import (
    verify_panel_token,
    ANTIGRAVITY_USER_AGENT,
    ANTIGRAVITY_CLIENT_ID,
    ANTIGRAVITY_CLIENT_SECRET,
)
from src.api.antigravity import fetch_quota_info, build_antigravity_headers
from src.httpx_client import post_async
from src.google_oauth_api import (
    Credentials,
    fetch_project_id_and_tier,
    get_user_email,
)
from config import get_antigravity_api_url


router = APIRouter(prefix="/creds", tags=["credentials"])


# =============================================================================
# Credential Import Core
# =============================================================================

async def _import_single_credential(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Import a single credential dictionary.
    Required: refresh_token
    Optional: email / tier / project_id (auto-discovered if missing)
    """
    try:
        refresh_token = (data.get("refresh_token") or "").strip()
        if not refresh_token:
            return {"status": "error", "message": "refresh_token tidak ditemukan"}

        email = (data.get("email") or "").strip().lower() or None
        tier = (data.get("tier") or "").strip().lower() or None
        project_id = (data.get("project_id") or "").strip() or None

        creds = Credentials(
            access_token="",
            refresh_token=refresh_token,
            client_id=ANTIGRAVITY_CLIENT_ID,
            client_secret=ANTIGRAVITY_CLIENT_SECRET,
        )
        try:
            await creds.refresh()
        except Exception as e:
            return {"status": "error", "message": f"refresh_token tidak valid: {str(e)[:200]}"}

        if not creds.access_token:
            return {"status": "error", "message": "refresh_token tidak valid: gagal memperoleh access_token"}

        if not email:
            try:
                email = await get_user_email(creds)
            except Exception as e:
                log.warning(f"Gagal mengambil email: {e}")
        if not email:
            return {"status": "error", "message": "Gagal mendapatkan alamat email dari akun"}

        if not project_id or not tier:
            try:
                api_base_url = await get_antigravity_api_url()
                fetched_project, fetched_tier = await fetch_project_id_and_tier(
                    access_token=creds.access_token,
                    user_agent=ANTIGRAVITY_USER_AGENT,
                    api_base_url=api_base_url,
                )
                if not project_id:
                    project_id = fetched_project
                if not tier:
                    tier = fetched_tier
            except Exception as e:
                log.warning(f"Gagal mengambil project_id/tier: {e}")

        if not project_id:
            log.warning(f"Import {email}: project_id fallback aicode-consumers")
            project_id = "aicode-consumers"

        credential_data = {
            "access_token": creds.access_token,
            "refresh_token": refresh_token,
            "client_id": ANTIGRAVITY_CLIENT_ID,
            "client_secret": ANTIGRAVITY_CLIENT_SECRET,
            "project_id": project_id,
            "expiry": creds.expires_at.isoformat() if creds.expires_at else "",
            "tier": tier,
        }

        await add_credential(email, credential_data)
        return {
            "status": "success",
            "email": email,
            "tier": tier,
            "message": "Berhasil mengimpor kredensial",
        }

    except Exception as e:
        return {"status": "error", "message": f"Gagal memproses: {str(e)[:200]}"}


# =============================================================================
# Utility Functions
# =============================================================================

async def extract_json_files_from_zip(zip_file: UploadFile) -> List[dict]:
    """Extract JSON files from uploaded ZIP archive."""
    try:
        zip_content = await zip_file.read()
        files_data = []

        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zip_ref:
            file_list = zip_ref.namelist()
            json_files = [
                f for f in file_list if f.endswith(".json") and not f.startswith("__MACOSX/")
            ]

            if not json_files:
                raise HTTPException(status_code=400, detail="Berkas JSON tidak ditemukan di dalam berkas ZIP")

            log.info(f"Found {len(json_files)} JSON files in ZIP {zip_file.filename}")

            for json_filename in json_files:
                try:
                    with zip_ref.open(json_filename) as json_file:
                        content = json_file.read()

                        try:
                            content_str = content.decode("utf-8")
                        except UnicodeDecodeError:
                            log.warning(f"Skipping incorrectly encoded file: {json_filename}")
                            continue

                        filename = json_filename.rsplit("/", 1)[-1]
                        files_data.append({"filename": filename, "content": content_str})

                except Exception as e:
                    log.warning(f"Error processing {json_filename} from ZIP: {e}")
                    continue

        log.info(f"Extracted {len(files_data)} valid JSON files from ZIP")
        return files_data

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Format berkas ZIP tidak valid")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        log.error(f"Failed to process ZIP file: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses berkas ZIP: {str(e)}")


async def upload_credentials_common(files: List[UploadFile]) -> JSONResponse:
    """Batch import credentials from JSON/ZIP files."""
    if not files:
        raise HTTPException(status_code=400, detail="Silakan pilih berkas untuk diunggah")

    if len(files) > 100:
        raise HTTPException(
            status_code=400, detail=f"Jumlah berkas terlalu banyak. Maksimal 100 berkas, saat ini: {len(files)}"
        )

    files_data = []
    for file in files:
        if file.filename.endswith(".zip"):
            zip_files_data = await extract_json_files_from_zip(file)
            files_data.extend(zip_files_data)
            log.info(f"Extracted {len(zip_files_data)} JSON files from {file.filename}")

        elif file.filename.endswith(".json"):
            content_chunks = []
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                content_chunks.append(chunk)

            content = b"".join(content_chunks)
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400, detail=f"Encoding berkas {file.filename} tidak didukung"
                )

            files_data.append({"filename": file.filename, "content": content_str})
        else:
            raise HTTPException(
                status_code=400, detail=f"Format berkas {file.filename} tidak didukung. Hanya mendukung berkas JSON dan ZIP"
            )

    batch_size = 100
    all_results = []
    total_success = 0

    for i in range(0, len(files_data), batch_size):
        batch_files = files_data[i : i + batch_size]

        async def process_single_file(file_data):
            try:
                data = json.loads(file_data["content"])
                if not isinstance(data, dict):
                    return {
                        "filename": file_data["filename"],
                        "status": "error",
                        "message": "Format JSON tidak valid: tingkat teratas harus berupa objek",
                    }
                result = await _import_single_credential(data)
                result["filename"] = file_data["filename"]
                return result
            except json.JSONDecodeError as e:
                return {
                    "filename": file_data["filename"],
                    "status": "error",
                    "message": f"Kesalahan parsing JSON: {str(e)}",
                }
            except Exception as e:
                return {
                    "filename": file_data["filename"],
                    "status": "error",
                    "message": f"Gagal memproses: {str(e)[:200]}",
                }

        log.info(f"Processing batch of {len(batch_files)} credentials concurrently...")
        concurrent_tasks = [process_single_file(file_data) for file_data in batch_files]
        batch_results = await asyncio.gather(*concurrent_tasks, return_exceptions=True)

        batch_uploaded_count = 0
        for result in batch_results:
            if isinstance(result, Exception):
                all_results.append(
                    {
                        "filename": "unknown",
                        "status": "error",
                        "message": f"Eksepsi pemrosesan: {str(result)[:200]}",
                    }
                )
            else:
                all_results.append(result)
                if result["status"] == "success":
                    batch_uploaded_count += 1

        total_success += batch_uploaded_count

        batch_num = (i // batch_size) + 1
        total_batches = (len(files_data) + batch_size - 1) // batch_size
        log.info(
            f"Batch {batch_num}/{total_batches} complete: "
            f"{batch_uploaded_count}/{len(batch_files)} successful"
        )

    return JSONResponse(
        content={
            "uploaded_count": total_success,
            "total_count": len(files_data),
            "results": all_results,
            "message": f"Impor massal selesai: Berhasil {total_success}/{len(files_data)} kredensial",
        }
    )


async def get_creds_status_common(
    offset: int, limit: int, status_filter: str,
    error_code_filter: str = None, cooldown_filter: str = None, tier_filter: str = None
) -> JSONResponse:
    """Retrieve credentials summary with pagination and filters."""
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset harus lebih besar atau sama dengan 0")
    if limit not in [20, 50, 100, 200, 500, 1000]:
        raise HTTPException(status_code=400, detail="limit hanya boleh bernilai 20, 50, 100, 200, 500, atau 1000")
    if status_filter not in ["all", "enabled", "disabled"]:
        raise HTTPException(status_code=400, detail="status_filter hanya boleh all, enabled, atau disabled")
    if cooldown_filter and cooldown_filter not in ["all", "in_cooldown", "no_cooldown"]:
        raise HTTPException(status_code=400, detail="cooldown_filter hanya boleh all, in_cooldown, atau no_cooldown")
    if tier_filter and tier_filter not in ["all", "free", "pro", "ultra"]:
        raise HTTPException(status_code=400, detail="tier_filter hanya boleh all, free, pro, atau ultra")

    database = await get_database()
    result = await database.get_credentials_summary(
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        error_code_filter=error_code_filter if error_code_filter and error_code_filter != "all" else None,
        cooldown_filter=cooldown_filter if cooldown_filter and cooldown_filter != "all" else None,
        tier_filter=tier_filter if tier_filter and tier_filter != "all" else None
    )

    return JSONResponse(content={
        "items": result["items"],
        "total": result["total"],
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < result["total"],
        "stats": result.get("stats", {"total": 0, "normal": 0, "disabled": 0}),
    })


async def download_all_creds_common() -> Response:
    """Archive and export all credentials as ZIP archive."""
    zip_filename = "antigravity_credentials.zip"

    database = await get_database()
    emails = await database.list_credentials()

    if not emails:
        raise HTTPException(status_code=404, detail="Tidak ada kredensial yang ditemukan")

    log.info(f"Packaging {len(emails)} credentials into ZIP archive...")

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        success_count = 0
        for email in emails:
            try:
                state = await database.get_credential_state(email)
                export_data = {
                    "refresh_token": "",
                    "email": email,
                    "tier": state.get("tier", "pro"),
                    "project_id": state.get("project_id", ""),
                }
                cred = await database.get_credential(email)
                if cred:
                    export_data["refresh_token"] = cred.get("refresh_token", "")
                else:
                    continue

                content = json.dumps(export_data, ensure_ascii=False, indent=2)
                zip_file.writestr(f"{email}.json", content)
                success_count += 1
            except Exception as e:
                log.warning(f"Error exporting credential {email}: {e}")
                continue

    log.info(f"Packaging complete: {success_count}/{len(emails)} credentials packaged")

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"},
    )


async def verify_credential_project_common(email: str) -> JSONResponse:
    """Re-verify credential Project ID and Tier from Google APIs."""
    database = await get_database()

    credential_data = await database.get_credential(email)
    if not credential_data:
        raise HTTPException(status_code=404, detail="Kredensial tidak ditemukan")

    credentials = Credentials.from_dict(credential_data)

    token_refreshed = await credentials.refresh_if_needed()

    if token_refreshed:
        log.info(f"Token refreshed automatically: {email}")
        credential_data = credentials.to_dict()
        await database.store_credential(email, credential_data)

    api_base_url = await get_antigravity_api_url()
    project_id, subscription_tier = await fetch_project_id_and_tier(
        access_token=credentials.access_token,
        user_agent=ANTIGRAVITY_USER_AGENT,
        api_base_url=api_base_url,
    )

    if not project_id:
        log.warning(f"Verify credential {email}: project_id failed, fallback to aicode-consumers")
        project_id = "aicode-consumers"

    if not subscription_tier:
        old_state = await database.get_credential_state(email)
        subscription_tier = old_state.get("tier") or "pro"
        log.warning(f"Verify credential {email}: tier discovery failed, retaining {subscription_tier}")

    credential_data["project_id"] = project_id
    await database.store_credential(email, credential_data)

    state_update = {
        "disabled": False,
        "error_codes": [],
        "tier": subscription_tier,
        "project_id": project_id,
    }

    await database.update_credential_state(email, state_update)

    log.info(f"Verified credential {email}: project_id={project_id}, tier={subscription_tier}")

    return JSONResponse(content={
        "success": True,
        "email": email,
        "project_id": project_id,
        "subscription_tier": subscription_tier,
        "message": "Verifikasi berhasil! Status dinonaktifkan telah dicabut dan kode error dibersihkan",
    })


# =============================================================================
# Route Handlers
# =============================================================================

@router.post("/upload")
async def upload_credentials(
    files: List[UploadFile] = File(...),
    token: str = Depends(verify_panel_token),
):
    """Batch upload credentials."""
    try:
        return await upload_credentials_common(files)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengunggah kredensial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_creds_status(
    token: str = Depends(verify_panel_token),
    offset: int = 0,
    limit: int = 50,
    status_filter: str = "all",
    error_code_filter: str = "all",
    cooldown_filter: str = "all",
    tier_filter: str = "all"
):
    """Get credentials status summary."""
    try:
        return await get_creds_status_common(
            offset, limit, status_filter,
            error_code_filter=error_code_filter,
            cooldown_filter=cooldown_filter,
            tier_filter=tier_filter
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal memuat status kredensial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/action")
async def creds_action(
    request: CredFileActionRequest,
    token: str = Depends(verify_panel_token)
):
    """Execute single action on credential (enable/disable/delete)."""
    try:
        email = request.email
        action = request.action

        log.info(f"Performing action '{action}' on credential: {email}")

        if action == "enable":
            result = await set_cred_disabled(email, False)
            if result:
                return JSONResponse(content={"message": f"Kredensial {email} berhasil diaktifkan"})
            raise HTTPException(status_code=500, detail="Gagal mengaktifkan kredensial, akun mungkin tidak ditemukan")

        elif action == "disable":
            result = await set_cred_disabled(email, True)
            if result:
                return JSONResponse(content={"message": f"Kredensial {email} berhasil dinonaktifkan"})
            raise HTTPException(status_code=500, detail="Gagal menonaktifkan kredensial, akun mungkin tidak ditemukan")

        elif action == "delete":
            success = await remove_credential(email)
            if success:
                return JSONResponse(content={"message": f"Kredensial {email} berhasil dihapus"})
            raise HTTPException(status_code=500, detail="Gagal menghapus kredensial")

        else:
            raise HTTPException(status_code=400, detail="Tipe operasi tidak valid")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengeksekusi operasi kredensial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-action")
async def creds_batch_action(
    request: CredFileBatchActionRequest,
    token: str = Depends(verify_panel_token)
):
    """Execute batch operations on credentials."""
    try:
        action = request.action
        emails = request.emails

        if not emails:
            raise HTTPException(status_code=400, detail="Daftar kredensial tidak boleh kosong")

        log.info(f"Executing batch action '{action}' on {len(emails)} credentials")

        success_count = 0
        errors = []

        for email in emails:
            try:
                if action == "enable":
                    await set_cred_disabled(email, False)
                    success_count += 1
                elif action == "disable":
                    await set_cred_disabled(email, True)
                    success_count += 1
                elif action == "delete":
                    if await remove_credential(email):
                        success_count += 1
                    else:
                        errors.append(f"{email}: Gagal menghapus")
                        continue
                else:
                    errors.append(f"{email}: Tipe tindakan tidak valid")
                    continue
            except Exception as e:
                log.error(f"Error handling {email}: {e}")
                errors.append(f"{email}: Gagal memproses - {str(e)}")
                continue

        result_message = f"Operasi massal selesai: Berhasil memproses {success_count}/{len(emails)} kredensial"
        if errors:
            result_message += "\nRincian error:\n" + "\n".join(errors)

        return JSONResponse(content={
            "success_count": success_count,
            "total_count": len(emails),
            "errors": errors,
            "message": result_message,
        })

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal menjalankan operasi massal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/{email}")
async def export_credential(
    email: str,
    token: str = Depends(verify_panel_token)
):
    """Export single credential as JSON."""
    try:
        database = await get_database()
        cred = await database.get_credential(email)
        if not cred:
            raise HTTPException(status_code=404, detail="Kredensial tidak ditemukan")

        state = await database.get_credential_state(email)
        export_data = {
            "refresh_token": cred.get("refresh_token", ""),
            "email": email,
            "tier": state.get("tier", "pro"),
            "project_id": cred.get("project_id", ""),
        }

        content = json.dumps(export_data, ensure_ascii=False, indent=2)

        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{email}.json"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengekspor kredensial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-all")
async def download_all_creds(token: str = Depends(verify_panel_token)):
    """Package and download all credentials as ZIP archive."""
    try:
        return await download_all_creds_common()
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengunduh arsip kredensial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-project/{email}")
async def verify_credential_project(
    email: str,
    token: str = Depends(verify_panel_token)
):
    """Verify and refresh credential project ID and tier."""
    try:
        return await verify_credential_project_common(email)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal memverifikasi kredensial {email}: {e}")
        raise HTTPException(status_code=500, detail=f"Verifikasi gagal: {str(e)}")


@router.get("/errors/{email}")
async def get_credential_errors(
    email: str,
    token: str = Depends(verify_panel_token)
):
    """Retrieve error history and diagnostic logs for credential."""
    try:
        database = await get_database()
        error_info = await database.get_credential_errors(email)
        return JSONResponse(content=error_info)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengambil rincian error {email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quota/{email}")
async def get_credential_quota(
    email: str,
    token: str = Depends(verify_panel_token)
):
    """Query remaining quota and model limits for credential."""
    try:
        database = await get_database()
        credential_data = await database.get_credential(email)
        if not credential_data:
            raise HTTPException(status_code=404, detail="Kredensial tidak ditemukan")

        creds = Credentials.from_dict(credential_data)
        await creds.refresh_if_needed()

        updated_data = creds.to_dict()
        if updated_data != credential_data:
            log.info(f"Token refreshed automatically: {email}")
            await database.store_credential(email, updated_data)
            credential_data = updated_data

        access_token = credential_data.get("access_token") or credential_data.get("token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Kredensial tidak memiliki access token")

        quota_info = await fetch_quota_info(access_token, credential_data.get("project_id", ""))

        if quota_info.get("success"):
            result = {
                "success": True,
                "email": email,
                "models": quota_info.get("models", {})
            }
            for extra_key in ("minResetDays", "accountTier", "isPro", "quotaGroups", "source"):
                if extra_key in quota_info:
                    result[extra_key] = quota_info[extra_key]
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "email": email,
                    "error": quota_info.get("error", "Kesalahan tidak diketahui")
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal mengambil informasi kuota {email}: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memperoleh kuota: {str(e)}")


@router.post("/test/{email}")
async def test_credential(
    email: str,
    _token: str = Depends(verify_panel_token)
):
    """
    Test live connectivity for credential against internal model endpoint.
    """
    try:
        database = await get_database()
        credential_data = await database.get_credential(email)
        if not credential_data:
            raise HTTPException(status_code=404, detail="Kredensial tidak ditemukan")

        credentials = Credentials.from_dict(credential_data)
        token_refreshed = await credentials.refresh_if_needed()

        if token_refreshed:
            log.info(f"Token refreshed automatically: {email}")
            credential_data = credentials.to_dict()
            await database.store_credential(email, credential_data)

        access_token = credential_data.get("access_token") or credential_data.get("token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Kredensial tidak memiliki access token")

        project_id = credential_data.get("project_id", "")
        if not project_id:
            raise HTTPException(status_code=400, detail="Kredensial tidak memiliki project ID")

        test_model = "gemini-2.5-flash-lite"
        api_base_url = await get_antigravity_api_url()
        headers = build_antigravity_headers(access_token)

        response = await post_async(
            url=f"{api_base_url}/v1internal:generateContent",
            json={
                "model": test_model,
                "project": project_id,
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": "hi"}]}]
                }
            },
            headers=headers,
            timeout=30.0
        )

        status_code = response.status_code

        if status_code == 200 or status_code == 429:
            log.info(f"Credential test succeeded: {email} (status={status_code})")
            if status_code == 200:
                await database.update_credential_state(email, {
                    "error_codes": [],
                    "error_messages": {}
                })

            return JSONResponse(
                status_code=status_code,
                content={
                    "success": True,
                    "status_code": status_code,
                    "message": "Uji coba berhasil",
                    "email": email
                }
            )
        else:
            log.warning(f"Credential test failed: {email} (status={status_code})")
            try:
                error_text = response.text if hasattr(response, "text") else ""
                error_codes = [status_code]
                error_messages = {str(status_code): error_text if error_text else f"HTTP {status_code}"}

                await database.update_credential_state(email, {
                    "error_codes": error_codes,
                    "error_messages": error_messages
                })
            except Exception as e:
                log.error(f"Failed to record test error: {e}")

        error_text = response.text if hasattr(response, "text") else ""

        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "status_code": status_code,
                "message": f"Uji coba gagal: HTTP {status_code}",
                "error": error_text,
                "email": email
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal menguji kredensial {email}: {e}")
        raise HTTPException(status_code=500, detail=f"Uji coba gagal: {str(e)}")
