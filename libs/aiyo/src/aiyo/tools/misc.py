"""Miscellaneous tools: time and thinking."""

from datetime import datetime

from ._markers import gatherable


@gatherable
async def get_current_time() -> str:
    """Return the current date and time in ISO 8601 format."""
    return datetime.now().isoformat(timespec="seconds")


@gatherable
async def think(thought: str) -> str:
    """Record an internal thought or reasoning step without producing output.

    Use this to think through a problem step by step before acting. The thought
    is logged and acknowledged but does not affect the environment.

    Args:
        thought: The thought or reasoning to record.
    """
    return "Thought logged."
