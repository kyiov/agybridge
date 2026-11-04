"""
Version Information Route Module - Handles /version/* HTTP requests
"""

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from log import log
from src.httpx_client import get_async


router = APIRouter(prefix="/version", tags=["version"])


@router.get("/info")
async def get_version_info(check_update: bool = False):
    """
    Get current version metadata from version.txt.
    Optional query param check_update: checks remote repository for newer commits.
    """
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        version_file = os.path.join(project_root, "version.txt")

        if not os.path.exists(version_file):
            return JSONResponse({
                "success": False,
                "error": "Berkas version.txt tidak ditemukan"
            })

        version_data = {}
        with open(version_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    version_data[key] = value

        if 'short_hash' not in version_data:
            return JSONResponse({
                "success": False,
                "error": "Format version.txt tidak valid"
            })

        response_data = {
            "success": True,
            "version": version_data.get('short_hash', 'unknown'),
            "full_hash": version_data.get('full_hash', ''),
            "message": version_data.get('message', ''),
            "date": version_data.get('date', '')
        }

        if check_update:
            update_url = os.getenv("VERSION_CHECK_URL")
            if not update_url:
                response_data['check_update'] = True
                response_data['has_update'] = False
                response_data['latest_version'] = version_data.get('short_hash', '')
            else:
                try:
                    resp = await get_async(update_url, timeout=10.0)
                    if resp.status_code == 200:
                        remote_version_data = {}
                        for line in resp.text.strip().split('\n'):
                            line = line.strip()
                            if '=' in line:
                                key, value = line.split('=', 1)
                                remote_version_data[key] = value

                        latest_hash = remote_version_data.get('full_hash', '')
                        latest_short_hash = remote_version_data.get('short_hash', '')
                        current_hash = version_data.get('full_hash', '')

                        has_update = (current_hash != latest_hash) if current_hash and latest_hash else False

                        response_data['check_update'] = True
                        response_data['has_update'] = has_update
                        response_data['latest_version'] = latest_short_hash
                        response_data['latest_hash'] = latest_hash
                        response_data['latest_message'] = remote_version_data.get('message', '')
                        response_data['latest_date'] = remote_version_data.get('date', '')
                    else:
                        response_data['check_update'] = False
                        response_data['update_error'] = f"Update server returned status {resp.status_code}"
                except Exception as e:
                    log.debug(f"Failed to check updates: {e}")
                    response_data['check_update'] = False
                    response_data['update_error'] = str(e)

        return JSONResponse(response_data)

    except Exception as e:
        log.error(f"Failed to retrieve version information: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        })
