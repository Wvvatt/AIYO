"""Miscellaneous tools: time and thinking."""

from datetime import datetime

from .tool_meta import tool


def _get_current_time_summary(_tool_args: dict[str, object]) -> str:
    return "current time"


def _think_summary(tool_args: dict[str, object]) -> str:
    return str(tool_args.get("thought", ""))[:80]


@tool(gatherable=True, summary=_get_current_time_summary)
async def get_current_time() -> str:
    """Return the current date and time in ISO 8601 format."""
    return datetime.now().isoformat(timespec="seconds")


@tool(gatherable=True, summary=_think_summary)
async def think(thought: str) -> str:
    """Record an internal thought or reasoning step without producing output.

    Use this to think through a problem step by step before acting. The thought
    is logged and acknowledged but does not affect the environment.

    Args:
        thought: The thought or reasoning to record.
    """
    return "Thought logged."
