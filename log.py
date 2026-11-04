"""
Logging Module - Pure console output
- LOG_LEVEL controls logging threshold (debug/info/warning/error/critical, default: info)
- ENABLE_LOG=0 silences console logging
- log.debug/info/warning/error/critical(message)
- set_log_level dynamically changes level, get_log_level returns current level
"""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

# Log level mappings
LOG_LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

_cached_log_level: int = LOG_LEVELS["info"]
_log_enabled: bool = True


def _refresh_config():
    """Refresh cached configuration from environment variables."""
    global _cached_log_level, _log_enabled
    level = os.getenv("LOG_LEVEL", "info").lower()
    _cached_log_level = LOG_LEVELS.get(level, LOG_LEVELS["info"])
    _log_enabled = os.getenv("ENABLE_LOG", "1").strip().lower() not in ("0", "false", "no", "off")


_refresh_config()


def _log(level: str, message: str):
    if not _log_enabled:
        return

    level_val = LOG_LEVELS.get(level.lower())
    if level_val is None:
        return

    if level_val < _cached_log_level:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level.upper()}] {message}"

    if level in ("error", "critical"):
        print(entry, file=sys.stderr)
    else:
        print(entry)


def set_log_level(level: str):
    """Dynamically set log level threshold."""
    global _cached_log_level
    level = level.lower()
    if level not in LOG_LEVELS:
        return False
    _cached_log_level = LOG_LEVELS[level]
    return True


def get_log_level() -> str:
    """Get current log level name."""
    current = _cached_log_level
    for name, value in LOG_LEVELS.items():
        if value == current:
            return name
    return "info"


# Logging interface: log.debug/info/warning/error/critical(message)
log = SimpleNamespace(
    debug=lambda message: _log("debug", message),
    info=lambda message: _log("info", message),
    warning=lambda message: _log("warning", message),
    error=lambda message: _log("error", message),
    critical=lambda message: _log("critical", message),
)

__all__ = ["log", "set_log_level", "get_log_level", "LOG_LEVELS"]
