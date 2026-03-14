"""Environment variable utilities."""

from __future__ import annotations

import os


def get_env_bool(name: str, default: bool = False) -> bool:
    """Get a boolean value from an environment variable.
    
    Args:
        name: The name of the environment variable.
        default: The default value if the variable is not set.
        
    Returns:
        True if the variable is set to a truthy value, False otherwise.
    """
    value = os.environ.get(name, "").lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")
