"""Agent mode — controls which tools are available to the LLM based on the current mode.

Design:

- ``AgentMode`` — the enum of modes (READONLY, NORMAL, PLAN).
- ``ModeState`` — owns the current mode and answers two questions that the
  guardrail middleware asks:
    1. ``allowed_tool_names(names)`` — given the full set of tool names, which
       are permitted in the current mode? (static, name-only filter)
    2. ``validate_tool_call(name, args)`` — raise ``ToolBlockedError`` if the
       specific call is disallowed. (per-call, may inspect arguments — e.g.
       PLAN mode restricts ``write_file`` paths to ``.plan/``)
- ``ModeMiddleware`` — mode-agnostic. On ``on_chat_start`` it narrows
  ``ctx.tools`` via ``allowed_tool_names`` and injects any pending mode-switch
  prompt. On ``on_tool_call_start`` it delegates to ``validate_tool_call`` as
  an execution-time safety net.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from aiyo.config import settings

from .exceptions import ToolBlockedError
from .middleware import ChatStartContext, Middleware, ToolCallStartContext


class AgentMode(Enum):
    """Agent tool access modes.

    READONLY  — read-only tools only; all write operations blocked.
    NORMAL    — full read/write access.
    PLAN      — write restricted to the '.plan/' directory; shell blocked.
    """

    READONLY = "readonly"
    NORMAL = "normal"
    PLAN = "plan"


_MODE_PROMPTS: dict[AgentMode, str] = {
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

    def allowed_tool_names(self, all_tool_names: frozenset[str]) -> frozenset[str]:
        """Return the subset of tool names allowed in the current mode.

        This is a static, name-only filter applied to the tool list the LLM
        sees. Argument-level restrictions live in ``validate_tool_call``.
        """
        if self.mode is AgentMode.READONLY:
            return frozenset(n for n in all_tool_names if n not in _WRITE_TOOL_NAMES)
        if self.mode is AgentMode.PLAN:
            return frozenset(n for n in all_tool_names if n != "shell")
        return all_tool_names

    def validate_tool_call(self, name: str, args: dict[str, object]) -> None:
        """Raise ``ToolBlockedError`` if this specific call is disallowed.

        Called at ``on_tool_call_start``. The name-level allowlist has already
        narrowed what the LLM can request, so this method exists mostly for
        (a) a safety net in case a disallowed tool slips through and (b)
        argument-level rules like PLAN mode's ``.plan/`` path restriction.
        """
        mode = self.mode
        if mode is AgentMode.READONLY and name in _WRITE_TOOL_NAMES:
            raise ToolBlockedError(
                f"[READONLY MODE] Tool '{name}' is not available in read-only mode."
            )
        if mode is AgentMode.PLAN:
            if name == "shell":
                raise ToolBlockedError(
                    "[PLAN MODE] Shell commands are blocked in plan mode. "
                    "Use write_file or edit_file with path='.plan/...' instead."
                )
            if name in ("write_file", "edit_file"):
                path = str(args.get("path", "") or "")
                if not _is_plan_file(path):
                    raise ToolBlockedError(
                        f"[PLAN MODE] Can only modify files under '.plan/' directory. "
                        f"Attempted: {path}"
                    )


class ModeMiddleware(Middleware):
    """Enforces the tool-access policy exposed by ``ModeState``.

    - ``on_chat_start``      — narrows ``ctx.tools`` to the mode-allowed subset
                               and injects any pending mode-switch prompt.
    - ``on_tool_call_start`` — delegates to ``ModeState.validate_tool_call``
                               as an execution-time safety net.

    The middleware itself knows nothing about specific modes; all policy
    lives in ``ModeState``. To add a new mode, extend ``AgentMode`` and the
    two ``ModeState`` query methods — this class does not need to change.
    """

    def __init__(self, state: ModeState) -> None:
        self._state = state

    async def on_chat_start(self, ctx: ChatStartContext) -> None:
        all_names = frozenset(
            getattr(t, "__name__", "") for t in ctx.tools if getattr(t, "__name__", "")
        )
        allowed = self._state.allowed_tool_names(all_names)
        ctx.tools = [t for t in ctx.tools if getattr(t, "__name__", "") in allowed]

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
