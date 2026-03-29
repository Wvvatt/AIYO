"""Tool mode middleware — controls which tools are offered to the LLM based on current mode."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from aiyo.config import settings

from .exceptions import ToolBlockedError
from .middleware import Middleware


class AgentMode(Enum):
    """Agent tool access modes."""

    READONLY = "readonly"
    READWRITE = "readwrite"
    PLAN = "plan"


_MODE_PROMPTS = {
    AgentMode.READONLY: (
        "<system-reminder>\n"
        "Mode switched to READONLY. All write operations are blocked.\n"
        "</system-reminder>\n"
    ),
    AgentMode.READWRITE: (
        "<system-reminder>\n"
        "Mode switched to READWRITE. Full read and write access is available.\n"
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

_CYCLE = [AgentMode.READWRITE, AgentMode.PLAN, AgentMode.READONLY]


class ModeState:
    """Shared mode state owned by Agent, read by ToolsModeMiddleware."""

    def __init__(self, mode: AgentMode = AgentMode.READWRITE) -> None:
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
        from aiyo.tools import READ_TOOLS, WRITE_TOOLS, edit_file, write_file  # noqa: PLC0415

        if self.mode == AgentMode.READONLY:
            mode_tools = list(READ_TOOLS)
        elif self.mode == AgentMode.READWRITE:
            mode_tools = list(READ_TOOLS) + list(WRITE_TOOLS)
        else:  # PLAN
            mode_tools = list(READ_TOOLS) + [write_file, edit_file]

        mode_names = {fn.__name__ for fn in mode_tools}
        extra = [t for t in self._extra_tools if t.__name__ not in mode_names]
        self._active_tools = mode_tools + extra


class ToolsModeMiddleware(Middleware):
    """Intercepts chat start and tool calls based on shared ModeState.

    Responsibilities:
    - on_chat_start : replace agent tools with mode-appropriate subset; inject pending prompt
    - on_tool_call_start : block disallowed tools at execution time

    Mode state is owned by Agent via ModeState; this middleware only reads it.
    """

    _WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file", "shell"})

    def __init__(self, state: ModeState) -> None:
        self._state = state

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        active = self._state.active_tools
        if self._state.pending_prompt:
            prompt, self._state.pending_prompt = self._state.pending_prompt, None
            return prompt + user_message, active
        return user_message, active

    def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        mode = self._state.mode
        if mode == AgentMode.READONLY and tool_name in self._WRITE_TOOL_NAMES:
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
        return tool_name, tool_id, tool_args


def _is_plan_file(path: str) -> bool:
    if not path or not path.startswith(".plan/"):
        return False
    plan_root = (settings.work_dir / ".plan").resolve()
    target = (settings.work_dir / Path(path)).resolve()
    return target.is_relative_to(plan_root)
