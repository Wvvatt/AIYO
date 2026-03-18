"""Plan mode middleware - restricts write operations to .plan/ directory."""

from __future__ import annotations

from typing import Any

from .exceptions import ToolBlockedError
from .middleware_base import Middleware


class PlanModeMiddleware(Middleware):
    """Restrict WRITE_TOOLS to only operate on .plan file when in plan mode."""

    _WRITE_TOOLS = frozenset({"write_file", "str_replace_file", "shell"})

    def __init__(self) -> None:
        self._plan_mode = False

    def toggle(self) -> bool:
        """Toggle plan mode and return new state."""
        self._plan_mode = not self._plan_mode
        return self._plan_mode

    @property
    def is_active(self) -> bool:
        """Check if plan mode is active."""
        return self._plan_mode

    def _is_plan_file(self, path: str) -> bool:
        """Check if path is within workdir/.plan/ directory."""
        if not path:
            return False
        return path.startswith(".plan/")

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Add plan mode instructions and strip blocked tools when active."""
        if not self._plan_mode:
            return user_message, tools

        plan_prompt = (
            "<system-reminder>\n"
            "You are in PLAN MODE. "
            "Write operations (write_file, str_replace_file) are restricted to the '.plan/' directory only. "
            "Create your plan as markdown files under .plan/ directory.\n"
            "</system-reminder>\n"
        )
        allowed_tools = [t for t in tools if t.__name__ != "shell"]
        return plan_prompt + user_message, allowed_tools

    def on_tool_call_start(self, tool_name: str, tool_args: dict) -> tuple[str, dict]:
        """Block write operations outside .plan file when in plan mode."""
        if not self._plan_mode or tool_name not in self._WRITE_TOOLS:
            return tool_name, tool_args

        path = tool_args.get("path", "")
        if tool_name == "shell":
            raise ToolBlockedError(
                "[PLAN MODE] Shell commands are blocked in plan mode. "
                "Use write_file or str_replace_file with path='.plan/...' instead."
            )

        if not self._is_plan_file(path):
            raise ToolBlockedError(
                f"[PLAN MODE] Can only modify files under '.plan/' directory. Attempted: {path}"
            )

        return tool_name, tool_args
