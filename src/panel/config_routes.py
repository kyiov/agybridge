"""
Configuration Route Module - Handles /config/* HTTP requests
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

import config
from log import log
from src.models import ConfigSaveRequest
from src.storage.database import get_database
from src.utils import verify_panel_token
from .utils import get_env_locked_keys


router = APIRouter(prefix="/config", tags=["config"])


@router.get("/get")
async def get_config(token: str = Depends(verify_panel_token)):
    """Retrieve current runtime configuration merging database and environment overrides."""
    try:
        current_config = {}

        current_config["credentials_dir"] = await config.get_credentials_dir()
        current_config["proxy"] = await config.get_proxy_config() or ""

        current_config["oauth_proxy_url"] = await config.get_oauth_proxy_url()
        current_config["googleapis_proxy_url"] = await config.get_googleapis_proxy_url()
        current_config["antigravity_api_url"] = await config.get_antigravity_api_url()

        current_config["auto_ban_enabled"] = await config.get_auto_ban_enabled()
        current_config["auto_ban_error_codes"] = await config.get_auto_ban_error_codes()

        current_config["retry_429_max_retries"] = await config.get_retry_429_max_retries()
        current_config["retry_429_enabled"] = await config.get_retry_429_enabled()
        current_config["retry_429_interval"] = await config.get_retry_429_interval()
        current_config["anti_truncation_max_attempts"] = await config.get_anti_truncation_max_attempts()

        current_config["return_thoughts_to_frontend"] = await config.get_return_thoughts_to_frontend()

        current_config["sensitive_words_enabled"] = await config.get_sensitive_words_enabled()
        current_config["sensitive_words"] = await config.get_sensitive_words()

        current_config["ip_whitelist_enabled"] = await config.get_ip_whitelist_enabled()
        current_config["ip_whitelist"] = await config.get_ip_whitelist()

        current_config["model_rewrite_enabled"] = await config.get_model_rewrite_enabled()
        current_config["model_rewrite_rules"] = await config.get_model_rewrite_rules_config()

        current_config["usage_log_enabled"] = await config.get_usage_log_enabled()

        current_config["request_log_enabled"] = await config.get_request_log_enabled()
        current_config["request_log_error_codes"] = await config.get_request_log_error_codes()

        current_config["credential_select_mode"] = await config.get_credential_select_mode()

        current_config["host"] = await config.get_server_host()
        current_config["port"] = await config.get_server_port()
        current_config["api_password"] = await config.get_api_password()
        current_config["panel_password"] = await config.get_panel_password()

        database = await get_database()
        storage_config = await database.get_all_config()

        env_locked_keys = get_env_locked_keys()

        for key, value in storage_config.items():
            if key not in env_locked_keys:
                current_config[key] = value

        return JSONResponse(content={"config": current_config, "env_locked": list(env_locked_keys)})

    except Exception as e:
        log.error(f"Failed to retrieve configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
async def save_config(request: ConfigSaveRequest, token: str = Depends(verify_panel_token)):
    """Validate and persist modified configuration keys into the database."""
    try:
        new_config = request.config
        log.debug(f"Configuration payload keys: {list(new_config.keys())}")

        if "retry_429_max_retries" in new_config:
            if (
                not isinstance(new_config["retry_429_max_retries"], int)
                or new_config["retry_429_max_retries"] < 0
            ):
                raise HTTPException(status_code=400, detail="Maksimum percobaan ulang 429 harus berupa integer >= 0")

        if "retry_429_enabled" in new_config:
            if not isinstance(new_config["retry_429_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan retry 429 harus berupa nilai boolean")

        if "retry_429_interval" in new_config:
            try:
                interval = float(new_config["retry_429_interval"])
                if interval < 0 or interval > 3600:
                    raise HTTPException(status_code=400, detail="Interval retry 429 harus antara 0-3600 detik")
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Interval retry 429 harus berupa angka valid")

        if "anti_truncation_max_attempts" in new_config:
            if (
                not isinstance(new_config["anti_truncation_max_attempts"], int)
                or new_config["anti_truncation_max_attempts"] < 1
                or new_config["anti_truncation_max_attempts"] > 10
            ):
                raise HTTPException(
                    status_code=400, detail="Jumlah percobaan maksimal anti-truncation harus integer 1-10"
                )

        if "return_thoughts_to_frontend" in new_config:
            if not isinstance(new_config["return_thoughts_to_frontend"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan thinking tokens harus berupa boolean")

        if "sensitive_words_enabled" in new_config:
            if not isinstance(new_config["sensitive_words_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan filter kata sensitif harus berupa boolean")

        if "sensitive_words" in new_config:
            words = new_config["sensitive_words"]
            if not isinstance(words, list):
                raise HTTPException(status_code=400, detail="Daftar kata sensitif harus berupa array")

            cleaned_words = []
            for word in words:
                if not isinstance(word, str):
                    raise HTTPException(status_code=400, detail=f"Kata sensitif harus berupa string: {word!r}")
                word = word.strip()
                if not word:
                    continue
                try:
                    re.compile(re.escape(word), re.IGNORECASE | re.UNICODE)
                except re.error:
                    raise HTTPException(status_code=400, detail=f"Kata sensitif tidak valid: {word!r}")
                cleaned_words.append(word)
            new_config["sensitive_words"] = cleaned_words

        if "ip_whitelist_enabled" in new_config:
            if not isinstance(new_config["ip_whitelist_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan IP whitelist harus berupa boolean")

        if "ip_whitelist" in new_config:
            entries = new_config["ip_whitelist"]
            if not isinstance(entries, list):
                raise HTTPException(status_code=400, detail="IP whitelist harus berupa array")
            cleaned_entries = []
            for entry in entries:
                if not isinstance(entry, str):
                    raise HTTPException(status_code=400, detail=f"Entri IP whitelist harus berupa string: {entry!r}")
                entry = entry.strip()
                if not entry:
                    continue
                try:
                    config.parse_ip_whitelist_line(entry)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Entri IP whitelist tidak valid: {entry!r}")
                cleaned_entries.append(entry)
            new_config["ip_whitelist"] = cleaned_entries

        if "model_rewrite_enabled" in new_config:
            if not isinstance(new_config["model_rewrite_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan rewrite model harus berupa boolean")

        if "model_rewrite_rules" in new_config:
            rules = new_config["model_rewrite_rules"]
            if not isinstance(rules, list):
                raise HTTPException(status_code=400, detail="Aturan rewrite model harus berupa array [regex, replacement]")
            cleaned_rules = []
            for rule in rules:
                if not (isinstance(rule, (list, tuple)) and len(rule) == 2 and all(isinstance(x, str) for x in rule)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Setiap aturan harus berupa pasangan string [regex, replacement]: {rule!r}",
                    )
                pattern, replacement = rule[0].strip(), rule[1].strip()
                if not pattern or not replacement:
                    raise HTTPException(status_code=400, detail=f"Regex dan nama model pengganti tidak boleh kosong: {rule!r}")
                try:
                    re.compile(pattern)
                except re.error:
                    raise HTTPException(status_code=400, detail=f"Pola regex tidak valid: {pattern!r}")
                cleaned_rules.append([pattern, replacement])
            new_config["model_rewrite_rules"] = cleaned_rules

        if "usage_log_enabled" in new_config:
            if not isinstance(new_config["usage_log_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan log permintaan harus berupa boolean")

        if "request_log_enabled" in new_config:
            if not isinstance(new_config["request_log_enabled"], bool):
                raise HTTPException(status_code=400, detail="Pengaturan log detail payload harus berupa boolean")

        if "request_log_error_codes" in new_config:
            codes = new_config["request_log_error_codes"]
            if not isinstance(codes, list):
                raise HTTPException(status_code=400, detail="Error code log detail harus berupa array, cth: [400, 429]")
            cleaned_codes = []
            for code in codes:
                if isinstance(code, bool) or not isinstance(code, int) or code < 100 or code > 599:
                    raise HTTPException(status_code=400, detail=f"Error code harus integer antara 100-599: {code!r}")
                if code not in cleaned_codes:
                    cleaned_codes.append(code)
            new_config["request_log_error_codes"] = sorted(cleaned_codes)

        if "credential_select_mode" in new_config:
            mode = new_config["credential_select_mode"]
            if mode not in ("random", "cache", "sticky"):
                raise HTTPException(status_code=400, detail="Mode pemilihan kredensial harus salah satu dari: random / cache / sticky")

        if "host" in new_config:
            if not isinstance(new_config["host"], str) or not new_config["host"].strip():
                raise HTTPException(status_code=400, detail="Host server tidak boleh kosong")

        if "port" in new_config:
            if (
                not isinstance(new_config["port"], int)
                or new_config["port"] < 1
                or new_config["port"] > 65535
            ):
                raise HTTPException(status_code=400, detail="Port harus berupa integer antara 1-65535")

        if "api_password" in new_config:
            if not isinstance(new_config["api_password"], str):
                raise HTTPException(status_code=400, detail="Kata sandi API harus berupa string")

        if "panel_password" in new_config:
            if not isinstance(new_config["panel_password"], str):
                raise HTTPException(status_code=400, detail="Kata sandi panel harus berupa string")

        env_locked_keys = get_env_locked_keys()

        database = await get_database()
        for key, value in new_config.items():
            if key not in env_locked_keys:
                await database.set_config(key, value)
                if key in ("api_password", "panel_password"):
                    log.debug(f"Updated {key}")

        await config.reload_config()

        response_data = {
            "message": "Konfigurasi berhasil disimpan",
            "saved_config": {k: v for k, v in new_config.items() if k not in env_locked_keys},
        }

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Gagal menyimpan konfigurasi: {e}")
        raise HTTPException(status_code=500, detail=str(e))
