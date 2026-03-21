"""Plan mode middleware - restricts write operations to .plan/ directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiyo.config import settings

from .exceptions import ToolBlockedError
from .middleware_base import Middleware


class PlanModeMiddleware(Middleware):
    """Restrict write tools to .plan/ when plan mode is active."""

    _WRITE_TOOLS = frozenset({"write_file", "edit_file", "shell"})

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
        """Check if path resolves within workdir/.plan/ directory."""
        if not path:
            return False
        if not path.startswith(".plan/"):
            return False

        plan_root = (settings.work_dir / ".plan").resolve()
        target = (settings.work_dir / Path(path)).resolve()
        return target.is_relative_to(plan_root)

    @staticmethod
    def _filter_tools(tools: list[Any]) -> list[Any]:
        """Return tools exposed to the model while in plan mode."""
        return [tool for tool in tools if tool.__name__ != "shell"]

    def _validate_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Validate tool call under plan mode and raise if disallowed."""
        if tool_name not in self._WRITE_TOOLS:
            return
        if tool_name == "shell":
            raise ToolBlockedError(
                "[PLAN MODE] Shell commands are blocked in plan mode. "
                "Use write_file or edit_file with path='.plan/...' instead."
            )

        path = str(tool_args.get("path", "") or "")
        if not self._is_plan_file(path):
            raise ToolBlockedError(
                f"[PLAN MODE] Can only modify files under '.plan/' directory. Attempted: {path}"
            )

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Add plan mode instructions and strip blocked tools when active."""
        if not self._plan_mode:
            return user_message, tools

        plan_prompt = (
            "<system-reminder>\n"
            "You are in PLAN MODE. "
            "Write operations (write_file, edit_file) are restricted to the '.plan/' directory "
            "only. Create your plan as markdown files under .plan/ directory.\n"
            "</system-reminder>\n"
        )
        allowed_tools = self._filter_tools(tools)
        return plan_prompt + user_message, allowed_tools

    def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        """Block disallowed tool calls when in plan mode."""
        if not self._plan_mode:
            return tool_name, tool_id, tool_args

        self._validate_tool_call(tool_name, tool_args)
        return tool_name, tool_id, tool_args
