"""
Configuration constants for the AGYBridge proxy server.
Centralizes all runtime configuration to avoid duplication across modules.
"""

import ipaddress
import json
import os
import re
from typing import Any, Optional

from log import log

# Global configuration cache
_config_cache: dict[str, Any] = {}
_config_initialized = False

# Error codes triggering auto-ban by default
AUTO_BAN_ERROR_CODES = [403]

# ====================== Environment Variable Mappings ======================
ENV_MAPPINGS = {
    "CREDENTIALS_DIR": "credentials_dir",
    "PROXY": "proxy",
    "OAUTH_PROXY_URL": "oauth_proxy_url",
    "GOOGLEAPIS_PROXY_URL": "googleapis_proxy_url",
    "ANTIGRAVITY_API_URL": "antigravity_api_url",
    "AUTO_BAN": "auto_ban_enabled",
    "AUTO_BAN_ERROR_CODES": "auto_ban_error_codes",
    "RETRY_429_MAX_RETRIES": "retry_429_max_retries",
    "RETRY_429_ENABLED": "retry_429_enabled",
    "RETRY_429_INTERVAL": "retry_429_interval",
    "ANTI_TRUNCATION_MAX_ATTEMPTS": "anti_truncation_max_attempts",
    "RETURN_THOUGHTS_TO_FRONTEND": "return_thoughts_to_frontend",
    "SENSITIVE_WORDS": "sensitive_words",
    "SENSITIVE_WORDS_ENABLED": "sensitive_words_enabled",
    "IP_WHITELIST": "ip_whitelist",
    "IP_WHITELIST_ENABLED": "ip_whitelist_enabled",
    "MODEL_REWRITE_ENABLED": "model_rewrite_enabled",
    "MODEL_REWRITE_RULES": "model_rewrite_rules",
    "USAGE_LOG_ENABLED": "usage_log_enabled",
    "REQUEST_LOG_ENABLED": "request_log_enabled",
    "REQUEST_LOG_ERROR_CODES": "request_log_error_codes",
    "CREDENTIAL_SELECT_MODE": "credential_select_mode",
    "HOST": "host",
    "PORT": "port",
    "API_PASSWORD": "api_password",
    "PANEL_PASSWORD": "panel_password",
    "FALLBACK_ENABLED": "fallback_enabled",
    "FALLBACK_API_KEY": "fallback_api_key",
    "FALLBACK_BASE_URL": "fallback_base_url",
    "FALLBACK_MODEL": "fallback_model",
    "HEALTH_CHECK_ENABLED": "health_check_enabled",
    "HEALTH_CHECK_INTERVAL": "health_check_interval",
    "HEALTH_CHECK_TIMEOUT": "health_check_timeout",
    "STREAM_READ_TIMEOUT": "stream_read_timeout",
    "REQUEST_TIMEOUT": "request_timeout",
}


# ====================== Configuration System ======================

async def init_config():
    """Initialize configuration cache from persistent storage once at startup."""
    global _config_cache, _config_initialized

    if _config_initialized:
        return

    try:
        from src.storage.database import get_database
        database = await get_database()
        _config_cache = await database.get_all_config()
        _config_initialized = True
    except Exception:
        _config_cache = {}
        _config_initialized = True


async def reload_config():
    """Reload configuration cache after persistence changes."""
    global _config_cache, _config_initialized

    try:
        from src.storage.database import get_database
        database = await get_database()
        await database.reload_config_cache()
        _config_cache = await database.get_all_config()
        _config_initialized = True
    except Exception:
        pass


def _get_cached_config(key: str, default: Any = None) -> Any:
    return _config_cache.get(key, default)


async def get_config_value(key: str, default: Any = None, env_var: Optional[str] = None) -> Any:
    """Get configuration value with priority: ENV > Storage > default."""
    if not _config_initialized:
        await init_config()

    if env_var and os.getenv(env_var):
        return os.getenv(env_var)

    value = _get_cached_config(key)
    if value is not None:
        return value

    return default


async def get_proxy_config():
    """Get proxy configuration URL (http://, https://, socks5://, socks5h://)."""
    proxy_url = await get_config_value("proxy", env_var="PROXY")
    if not proxy_url:
        return None

    proxy_url = proxy_url.strip()
    scheme = proxy_url.split("://", 1)[0].lower()
    if scheme not in ("http", "https", "socks5", "socks5h"):
        log.warning(
            f"Unsupported proxy scheme: {scheme}:// (supported: http/https/socks5/socks5h), proxy ignored"
        )
        return None
    return proxy_url


async def get_auto_ban_enabled() -> bool:
    env_value = os.getenv("AUTO_BAN")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("auto_ban_enabled", False))


async def get_auto_ban_error_codes() -> list[int]:
    env_value = os.getenv("AUTO_BAN_ERROR_CODES")
    if env_value:
        try:
            return [int(code.strip()) for code in env_value.split(",") if code.strip()]
        except ValueError:
            pass

    codes = await get_config_value("auto_ban_error_codes", AUTO_BAN_ERROR_CODES)
    if isinstance(codes, list):
        return codes
    return AUTO_BAN_ERROR_CODES


async def get_retry_429_max_retries() -> int:
    env_value = os.getenv("RETRY_429_MAX_RETRIES")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass

    return int(await get_config_value("retry_429_max_retries", 5))


async def get_retry_429_enabled() -> bool:
    env_value = os.getenv("RETRY_429_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("retry_429_enabled", True))


async def get_retry_429_interval() -> float:
    env_value = os.getenv("RETRY_429_INTERVAL")
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            pass

    return float(await get_config_value("retry_429_interval", 1.0))


async def get_anti_truncation_max_attempts() -> int:
    env_value = os.getenv("ANTI_TRUNCATION_MAX_ATTEMPTS")
    if env_value:
        try:
            val = int(env_value)
            if 1 <= val <= 10:
                return val
        except ValueError:
            pass

    val = await get_config_value("anti_truncation_max_attempts", 3)
    try:
        val = int(val)
        return max(1, min(10, val))
    except (ValueError, TypeError):
        return 3


async def get_server_host() -> str:
    return str(await get_config_value("host", "0.0.0.0", "HOST"))


async def get_server_port() -> int:
    env_value = os.getenv("PORT")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass

    return int(await get_config_value("port", 7861))


async def get_api_password() -> str:
    return str(await get_config_value("api_password", "pwd", "API_PASSWORD"))


async def get_panel_password() -> str:
    return str(await get_config_value("panel_password", "pwd", "PANEL_PASSWORD"))


async def get_credentials_dir() -> str:
    return str(await get_config_value("credentials_dir", "./creds", "CREDENTIALS_DIR"))


async def get_return_thoughts_to_frontend() -> bool:
    env_value = os.getenv("RETURN_THOUGHTS_TO_FRONTEND")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("return_thoughts_to_frontend", True))


# ====================== Sensitive Words Filter ======================

_sensitive_words_cache: dict = {"fingerprint": None, "patterns": []}


async def get_sensitive_words_enabled() -> bool:
    env_value = os.getenv("SENSITIVE_WORDS_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("sensitive_words_enabled", False))


async def get_sensitive_words() -> list:
    env_value = os.getenv("SENSITIVE_WORDS")
    if env_value:
        return [w.strip() for w in re.split(r"[,\n]", env_value) if w.strip()]

    value = await get_config_value("sensitive_words")
    if isinstance(value, list):
        return [str(w) for w in value if str(w).strip()]
    if isinstance(value, str) and value.strip():
        return [w.strip() for w in re.split(r"[,\n]", value) if w.strip()]
    return []


def compile_sensitive_words(words: list):
    fingerprint = tuple(words)
    if _sensitive_words_cache["fingerprint"] == fingerprint:
        return _sensitive_words_cache["patterns"]

    patterns = []
    for word in words:
        word = str(word).strip()
        if not word:
            continue
        try:
            patterns.append(re.compile(re.escape(word), re.IGNORECASE | re.UNICODE))
        except re.error as e:
            log.warning(f"Failed to compile sensitive word pattern: {word!r} ({e})")

    _sensitive_words_cache["fingerprint"] = fingerprint
    _sensitive_words_cache["patterns"] = patterns
    return patterns


def apply_sensitive_word_filter(text: str, patterns) -> str:
    if not text or not patterns:
        return text
    for pattern in patterns:
        text = pattern.sub("", text)
    return text


async def get_sensitive_word_filter():
    if not await get_sensitive_words_enabled():
        return False, []
    words = await get_sensitive_words()
    if not words:
        return False, []
    return True, compile_sensitive_words(words)


# ====================== IP Whitelist ======================

_ip_whitelist_cache: dict = {"fingerprint": None, "result": ([], [])}


def parse_ip_whitelist_line(line: str):
    """
    Parse a single whitelist entry to (lo, hi, version) address range.
    Supports single IP, CIDR subnet, or hyphen/tilde range.
    """
    line = str(line).strip()
    if not line:
        raise ValueError("Empty entry")

    for sep in ("~", "-"):
        if sep in line:
            start_str, _, end_str = line.partition(sep)
            if start_str.strip() and end_str.strip():
                start = ipaddress.ip_address(start_str.strip())
                end = ipaddress.ip_address(end_str.strip())
                if start.version != end.version:
                    raise ValueError(f"Mismatched IP versions in range: {line}")
                if int(start) > int(end):
                    start, end = end, start
                return start, end, start.version

    if "/" in line:
        net = ipaddress.ip_network(line, strict=False)
        return net.network_address, net.broadcast_address, net.version

    addr = ipaddress.ip_address(line)
    return addr, addr, addr.version


def compile_ip_whitelist(entries: list):
    fingerprint = tuple(str(e) for e in entries)
    if _ip_whitelist_cache["fingerprint"] == fingerprint:
        return _ip_whitelist_cache["result"]

    rules = []
    invalid = []
    for entry in entries:
        entry = str(entry).strip()
        if not entry:
            continue
        try:
            rules.append(parse_ip_whitelist_line(entry))
        except ValueError:
            invalid.append(entry)

    result = (rules, invalid)
    _ip_whitelist_cache["fingerprint"] = fingerprint
    _ip_whitelist_cache["result"] = result
    return result


def ip_in_whitelist(client_ip: str, rules: list) -> bool:
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(lo.version == addr.version and lo <= addr <= hi for lo, hi, _ in rules)


async def get_ip_whitelist_enabled() -> bool:
    env_value = os.getenv("IP_WHITELIST_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("ip_whitelist_enabled", False))


async def get_ip_whitelist() -> list:
    env_value = os.getenv("IP_WHITELIST")
    if env_value is not None and env_value.strip():
        return [e.strip() for e in re.split(r"[,\n]", env_value) if e.strip()]

    value = await get_config_value("ip_whitelist")
    if isinstance(value, list):
        return [str(e).strip() for e in value if str(e).strip()]
    if isinstance(value, str) and value.strip():
        return [e.strip() for e in re.split(r"[,\n]", value) if e.strip()]
    return []


async def get_ip_whitelist_rules():
    if not await get_ip_whitelist_enabled():
        return False, []
    entries = await get_ip_whitelist()
    if not entries:
        return False, []
    rules, invalid = compile_ip_whitelist(entries)
    if invalid:
        log.warning(f"Skipping invalid IP whitelist entries: {invalid}")
    return bool(rules), rules


# ====================== Model Name Rewriting ======================

_model_rewrite_cache: dict = {"fingerprint": None, "result": ([], [])}


async def get_model_rewrite_enabled() -> bool:
    env_value = os.getenv("MODEL_REWRITE_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("model_rewrite_enabled", False))


async def get_model_rewrite_rules_config() -> list:
    env_value = os.getenv("MODEL_REWRITE_RULES")
    if env_value is not None and env_value.strip():
        parsed = _parse_model_rewrite_rules_value(env_value)
        if parsed is not None:
            return parsed

    value = await get_config_value("model_rewrite_rules")
    return _parse_model_rewrite_rules_value(value) or []


def _parse_model_rewrite_rules_value(value: Any) -> Optional[list]:
    if isinstance(value, list):
        rules = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(x, str) for x in item):
                rules.append([item[0], item[1]])
            elif isinstance(item, dict) and isinstance(item.get("pattern"), str) and isinstance(item.get("replacement"), str):
                rules.append([item["pattern"], item["replacement"]])
        return rules
    if isinstance(value, str) and value.strip():
        if value.strip().startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    inner = _parse_model_rewrite_rules_value(parsed)
                    if inner is not None:
                        return inner
            except (json.JSONDecodeError, ValueError):
                pass
        rules = []
        for pair in value.split(","):
            pair = pair.strip()
            if "->" in pair:
                pat, _, rep = pair.partition("->")
                rules.append([pat.strip(), rep.strip()])
        return rules or None
    return None


def compile_model_rewrite_rules(rules: list):
    fingerprint = tuple(tuple(r) for r in rules)
    if _model_rewrite_cache["fingerprint"] == fingerprint:
        return _model_rewrite_cache["result"]

    compiled = []
    invalid = []
    for rule in rules:
        if not (isinstance(rule, (list, tuple)) and len(rule) == 2):
            continue
        pattern, replacement = rule[0], rule[1]
        try:
            compiled.append((re.compile(str(pattern)), str(replacement)))
        except re.error:
            invalid.append(rule)

    result = (compiled, invalid)
    _model_rewrite_cache["fingerprint"] = fingerprint
    _model_rewrite_cache["result"] = result
    return result


def rewrite_model_name(model_name: str, compiled_rules: list) -> str:
    for pattern, replacement in compiled_rules:
        if pattern.search(model_name):
            return pattern.sub(replacement, model_name)
    return model_name


async def get_model_rewrite_filter():
    if not await get_model_rewrite_enabled():
        return False, []
    rules = await get_model_rewrite_rules_config()
    if not rules:
        return False, []
    compiled, invalid = compile_model_rewrite_rules(rules)
    if invalid:
        log.warning(f"Skipping invalid model rewrite regexes: {invalid}")
    return bool(compiled), compiled


# ====================== Usage & Payload Logs ======================

async def get_usage_log_enabled() -> bool:
    env_value = os.getenv("USAGE_LOG_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("usage_log_enabled", True))


async def get_request_log_enabled() -> bool:
    env_value = os.getenv("REQUEST_LOG_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    return bool(await get_config_value("request_log_enabled", False))


async def get_request_log_error_codes() -> list:
    env_value = os.getenv("REQUEST_LOG_ERROR_CODES")
    if env_value:
        try:
            return [int(code.strip()) for code in env_value.split(",") if code.strip()]
        except ValueError:
            pass

    codes = await get_config_value("request_log_error_codes")
    if codes and isinstance(codes, list):
        return codes
    return [400]


# ====================== Credential Selection Mode ======================

CREDENTIAL_SELECT_MODES = ("random", "cache", "sticky")


async def get_credential_select_mode() -> str:
    value = await get_config_value("credential_select_mode", "cache", "CREDENTIAL_SELECT_MODE")
    value = str(value).strip().lower()
    if value not in CREDENTIAL_SELECT_MODES:
        log.warning(f"Invalid credential_select_mode: {value}, falling back to cache")
        return "cache"
    return value


async def get_oauth_proxy_url() -> str:
    return str(
        await get_config_value(
            "oauth_proxy_url", "https://oauth2.googleapis.com", "OAUTH_PROXY_URL"
        )
    )


async def get_googleapis_proxy_url() -> str:
    return str(
        await get_config_value(
            "googleapis_proxy_url", "https://www.googleapis.com", "GOOGLEAPIS_PROXY_URL"
        )
    )


async def get_antigravity_api_url() -> str:
    return str(
        await get_config_value(
            "antigravity_api_url",
            "https://daily-cloudcode-pa.googleapis.com",
            "ANTIGRAVITY_API_URL",
        )
    )


# ====================== Health Check & Fallback Configuration ======================

async def get_health_check_enabled() -> bool:
    env_value = os.getenv("HEALTH_CHECK_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")
    return bool(await get_config_value("health_check_enabled", True))


async def get_health_check_interval() -> int:
    env_value = os.getenv("HEALTH_CHECK_INTERVAL")
    if env_value:
        try:
            return max(10, int(env_value))
        except ValueError:
            pass
    return int(await get_config_value("health_check_interval", 180))


async def get_health_check_timeout() -> float:
    env_value = os.getenv("HEALTH_CHECK_TIMEOUT")
    if env_value:
        try:
            return max(1.0, float(env_value))
        except ValueError:
            pass
    return float(await get_config_value("health_check_timeout", 10.0))


async def get_stream_read_timeout() -> float:
    env_value = os.getenv("STREAM_READ_TIMEOUT")
    if env_value:
        try:
            return max(5.0, float(env_value))
        except ValueError:
            pass
    return float(await get_config_value("stream_read_timeout", 60.0))


async def get_request_timeout() -> float:
    env_value = os.getenv("REQUEST_TIMEOUT")
    if env_value:
        try:
            return max(5.0, float(env_value))
        except ValueError:
            pass
    return float(await get_config_value("request_timeout", 60.0))


async def get_fallback_enabled() -> bool:
    env_value = os.getenv("FALLBACK_ENABLED")
    if env_value:
        return env_value.lower() in ("true", "1", "yes", "on")

    stored = await get_config_value("fallback_enabled")
    if stored is not None:
        return bool(stored)

    # Auto-enable fallback if any fallback API key is configured
    keys = await get_fallback_api_keys()
    return len(keys) > 0


async def get_fallback_api_keys() -> list[str]:
    """Retrieve fallback API keys (from FALLBACK_API_KEY, FALLBACK_API_KEYS, or GEMINI_API_KEY)."""
    raw_keys: list[str] = []

    for env_var in ("FALLBACK_API_KEY", "FALLBACK_API_KEYS", "GEMINI_API_KEY"):
        val = os.getenv(env_var)
        if val and val.strip():
            raw_keys.append(val.strip())

    if not raw_keys:
        stored = await get_config_value("fallback_api_key")
        if stored and str(stored).strip():
            raw_keys.append(str(stored).strip())

    result: list[str] = []
    for k in raw_keys:
        for part in k.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result


async def get_fallback_base_url() -> str:
    env_value = os.getenv("FALLBACK_BASE_URL")
    if env_value and env_value.strip():
        return env_value.strip().rstrip("/")
    stored = await get_config_value("fallback_base_url", "https://generativelanguage.googleapis.com/v1beta")
    return str(stored).strip().rstrip("/")


async def get_fallback_model() -> str:
    env_value = os.getenv("FALLBACK_MODEL")
    if env_value and env_value.strip():
        return env_value.strip()
    return str(await get_config_value("fallback_model", "")).strip()

