"""Agent mode — controls which tools are available to the LLM based on the current mode."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from aiyo.config import settings

from .exceptions import ToolBlockedError
from .middleware import Middleware


class AgentMode(Enum):
    """Agent tool access modes.

    READONLY  — read-only tools only; all write operations blocked.
    NORMAL    — full read/write access.
    PLAN      — write restricted to the '.plan/' directory; shell blocked.
    """

    READONLY = "readonly"
    NORMAL = "normal"
    PLAN = "plan"


_MODE_PROMPTS = {
    AgentMode.READONLY: (
        "<system-reminder>\n"
        "Mode switched to READONLY. All write operations are blocked.\n"
        "</system-reminder>\n"
    ),
    AgentMode.NORMAL: (
        "<system-reminder>\n"
        "Mode switched to NORMAL. Full read and write access is available.\n"
        "</system-reminder>\n"
    ),
    AgentMode.PLAN: (
        "<system-reminder>\n"
        "Mode switched to PLAN MODE. "
        "Write operations (write_file, edit_file) are restricted to the '.plan/' directory only. "
        "Create your plan as markdown files under .plan/ directory.\n"
        "</system-reminder>\n"
    ),
}


_WRITE_TOOL_NAMES: frozenset[str] = frozenset({"write_file", "edit_file", "shell"})


class ModeState:
    """Shared mode state owned by Agent, read by ToolsModeMiddleware."""

    def __init__(self, mode: AgentMode = AgentMode.NORMAL) -> None:
        self.mode = mode
        self.pending_prompt: str | None = None
        self._active_tools: list[Callable[..., Any]] = []
        self._extra_tools: list[Callable[..., Any]] = []

    def set(self, mode: AgentMode) -> None:
        """Switch mode and queue the one-shot prompt for next on_chat_start."""
        self.mode = mode
        self.pending_prompt = _MODE_PROMPTS[mode]
        self._rebuild_tools()

    def init(self, mode: AgentMode, extra_tools: list[Callable[..., Any]]) -> None:
        """Called once at Agent init — sets initial mode without queuing a prompt."""
        self._extra_tools = extra_tools
        self.mode = mode
        self._rebuild_tools()

    @property
    def active_tools(self) -> list[Callable[..., Any]]:
        return self._active_tools

    def _rebuild_tools(self) -> None:
        from aiyo.tools import BUILTIN_TOOLS  # noqa: PLC0415

        if self.mode == AgentMode.READONLY:
            mode_tools = [t for t in BUILTIN_TOOLS if t.__name__ not in _WRITE_TOOL_NAMES]
        elif self.mode == AgentMode.NORMAL:
            mode_tools = list(BUILTIN_TOOLS)
        else:  # PLAN — write_file/edit_file allowed, shell blocked
            mode_tools = [t for t in BUILTIN_TOOLS if t.__name__ != "shell"]

        mode_names = {fn.__name__ for fn in mode_tools}
        extra = [t for t in self._extra_tools if t.__name__ not in mode_names]
        self._active_tools = mode_tools + extra


class ToolsModeMiddleware(Middleware):
    """Enforces tool access rules defined by ModeState.

    - on_chat_start      : narrows the tool list to the mode-appropriate subset;
                           injects any pending mode-switch prompt.
    - on_tool_call_start : blocks disallowed tools at execution time as a safety net.

    ModeState is owned by Agent; this middleware only reads it.
    """

    def __init__(self, state: ModeState) -> None:
        self._state = state

    async def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        active = self._state.active_tools
        if self._state.pending_prompt:
            prompt, self._state.pending_prompt = self._state.pending_prompt, None
            return prompt + user_message, active
        return user_message, active

    async def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any], summary: str = ""
    ) -> tuple[str, str, dict[str, Any], str]:
        mode = self._state.mode
        if mode == AgentMode.READONLY and tool_name in _WRITE_TOOL_NAMES:
            raise ToolBlockedError(
                f"[READONLY MODE] Tool '{tool_name}' is not available in read-only mode."
            )
        if mode == AgentMode.PLAN:
            if tool_name == "shell":
                raise ToolBlockedError(
                    "[PLAN MODE] Shell commands are blocked in plan mode. "
                    "Use write_file or edit_file with path='.plan/...' instead."
                )
            if tool_name in ("write_file", "edit_file"):
                path = str(tool_args.get("path", "") or "")
                if not _is_plan_file(path):
                    raise ToolBlockedError(
                        f"[PLAN MODE] Can only modify files under '.plan/' directory. "
                        f"Attempted: {path}"
                    )
        return tool_name, tool_id, tool_args, summary


def _is_plan_file(path: str) -> bool:
    if not path or not path.startswith(".plan/"):
        return False
    plan_root = (settings.work_dir / ".plan").resolve()
    target = (settings.work_dir / Path(path)).resolve()
    return target.is_relative_to(plan_root)
