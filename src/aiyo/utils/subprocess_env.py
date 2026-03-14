"""Subprocess environment utilities."""

from __future__ import annotations

import os


def get_clean_env() -> dict[str, str]:
    """Get a clean environment for subprocess execution.
    
    Removes AIYO-specific environment variables to avoid
    leaking internal state to subprocesses.
    """
    env = dict(os.environ)
    
    # Remove potentially problematic variables
    prefixes_to_remove = [
        "AIYO_",
    ]
    
    keys_to_remove = [
        k for k in env.keys()
        if any(k.startswith(prefix) for prefix in prefixes_to_remove)
    ]
    
    for key in keys_to_remove:
        del env[key]
    
    return env
