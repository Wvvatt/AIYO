"""Agent mode — controls which tools are available to the LLM based on the current mode.

Design:

- ``AgentMode`` — the enum of modes (NORMAL, PLAN).
- ``ModeState`` — owns the current mode and exposes ``validate_tool_call``
  for argument-level restrictions (e.g. PLAN mode's ``.plan/`` path check).
- ``ModeMiddleware`` — on ``on_chat_start`` it filters out tools marked with
  mode-specific markers (e.g. ``@not_for_planmode``) and injects any pending
  mode-switch prompt.  On ``on_tool_call_start`` it delegates to
  ``validate_tool_call`` as an execution-time safety net.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from aiyo.config import settings
from aiyo.tools._markers import is_not_for_planmode

from .exceptions import ToolBlockedError
from .middleware import ChatStartContext, Middleware, ToolCallStartContext


class AgentMode(Enum):
    """Agent tool access modes.

    NORMAL    — full read/write access.
    PLAN      — write restricted to the '.plan/' directory; shell blocked.
    """

    NORMAL = "normal"
    PLAN = "plan"


_MODE_PROMPTS: dict[AgentMode, str] = {
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


class ModeState:
    """Holds the active mode and answers tool-permission queries.

    Owned by ``Agent``; read by ``ModeMiddleware``.
    """

    def __init__(self, mode: AgentMode = AgentMode.NORMAL) -> None:
        self.mode = mode
        self.pending_prompt: str | None = None

    def set(self, mode: AgentMode) -> None:
        """Switch mode and queue the one-shot prompt for next on_chat_start."""
        self.mode = mode
        self.pending_prompt = _MODE_PROMPTS[mode]

    # ----- guardrail queries -----

    def validate_tool_call(self, name: str, args: dict[str, object]) -> None:
        """Raise ``ToolBlockedError`` if this specific call is disallowed.

        Called at ``on_tool_call_start`` as an execution-time safety net.
        Marker-based filtering (e.g. ``@not_for_planmode``) happens in
        ``ModeMiddleware.on_chat_start``; this method handles argument-level
        rules like PLAN mode's ``.plan/`` path restriction.
        """
        if self.mode is AgentMode.PLAN:
            if name in ("write_file", "edit_file"):
                path = str(args.get("path", "") or "")
                if not _is_plan_file(path):
                    raise ToolBlockedError(
                        f"[PLAN MODE] Can only modify files under '.plan/' directory. "
                        f"Attempted: {path}"
                    )


class ModeMiddleware(Middleware):
    """Enforces the tool-access policy exposed by ``ModeState`` and tool markers.

    - ``on_chat_start``      — filters out tools with mode-specific markers
                               (e.g. ``@not_for_planmode``) and injects any
                               pending mode-switch prompt.
    - ``on_tool_call_start`` — delegates to ``ModeState.validate_tool_call``
                               as an execution-time safety net.
    """

    def __init__(self, state: ModeState) -> None:
        self._state = state

    async def on_chat_start(self, ctx: ChatStartContext) -> None:
        if self._state.mode is AgentMode.PLAN:
            ctx.tools = [t for t in ctx.tools if not is_not_for_planmode(t)]

        if self._state.pending_prompt:
            prompt, self._state.pending_prompt = self._state.pending_prompt, None
            ctx.user_message = prompt + ctx.user_message

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        self._state.validate_tool_call(ctx.tool_name, ctx.tool_args)


def _is_plan_file(path: str) -> bool:
    if not path or not path.startswith(".plan/"):
        return False
    plan_root = (settings.work_dir / ".plan").resolve()
    target = (settings.work_dir / Path(path)).resolve()
    return target.is_relative_to(plan_root)
