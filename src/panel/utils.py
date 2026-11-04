"""
Panel Shared Utilities
"""

import os
from typing import Set

import config


def get_env_locked_keys() -> Set:
    """Get the set of configuration keys locked by environment variables."""
    env_locked_keys = set()

    for env_key, config_key in config.ENV_MAPPINGS.items():
        if os.getenv(env_key):
            env_locked_keys.add(config_key)

    return env_locked_keys
