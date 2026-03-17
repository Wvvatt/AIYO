"""UI middleware components."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from rich.syntax import Syntax

from aiyo import Middleware
from aiyo.agent.exceptions import ToolBlockedError

from .theme import CODE_THEME, console


class ToolDisplayMiddleware(Middleware):
    """Print tool calls to the console using Rich."""

    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        name = "".join(p.capitalize() for p in tool_name.split("_"))
        match tool_name:
            case "todo":
                console.print(f"[tool]{name}[/tool]\n[muted]{result}[/muted]")
            case "think":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('thought', '')}[/muted]")
            case "read_file" | "write_file" | "str_replace_file":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('path', '')}[/muted]")
            case "glob_files":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('pattern', '')}[/muted]")
            case "list_directory":
                console.print(
                    f"[tool]{name}[/tool] [muted]{tool_args.get('relative_path', '.')}[/muted]"
                )
            case "run_shell_command":
                cmd = tool_args.get("command", "")
                console.print(f"[tool]{name}[/tool] [muted]{cmd[:120]}[/muted]")
            case "load_skill":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('name', '')}[/muted]")
            case "jira_cli":
                cmd = tool_args.get("command", "")
                raw = tool_args.get("args") or {}
                if isinstance(raw, str):
                    import json as _json

                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {}
                issue = raw.get("issue_key", "")
                suffix = f" {issue}" if issue else ""
                console.print(f"[tool]{name}[/tool] [muted]{cmd}{suffix}[/muted]")
            case "confluence_cli":
                cmd = tool_args.get("command", "")
                raw = tool_args.get("args") or {}
                if isinstance(raw, str):
                    import json as _json

                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {}
                page_id = raw.get("page_id", "")
                suffix = f" {page_id}" if page_id else ""
                console.print(f"[tool]{name}[/tool] [muted]{cmd}{suffix}[/muted]")
            case "gerrit_cli":
                cmd = tool_args.get("command", "")
                raw = tool_args.get("args") or {}
                if isinstance(raw, str):
                    import json as _json

                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {}
                change_id = raw.get("change_id", "")
                suffix = f" {change_id}" if change_id else ""
                console.print(f"[tool]{name}[/tool] [muted]{cmd}{suffix}[/muted]")
            case _:
                console.print(f"[tool]{name}[/tool]")
        return result


class PlanModeMiddleware(Middleware):
    """Restrict WRITE_TOOLS to only operate on .plan file when in plan mode."""

    _WRITE_TOOLS = frozenset({"write_file", "str_replace_file", "run_shell_command"})

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
            "[SYSTEM: You are in PLAN MODE. "
            "Write operations (write_file, str_replace_file) are restricted to the '.plan/' directory only. "
            "Create your plan as markdown files under .plan/ directory.]\n"
        )
        allowed_tools = [t for t in tools if t.__name__ != "run_shell_command"]
        return plan_prompt + user_message, allowed_tools

    def on_tool_call_start(self, tool_name: str, tool_args: dict) -> tuple[str, dict]:
        """Block write operations outside .plan file when in plan mode."""
        if not self._plan_mode or tool_name not in self._WRITE_TOOLS:
            return tool_name, tool_args

        path = tool_args.get("path", "")
        if tool_name == "run_shell_command":
            raise ToolBlockedError(
                "[PLAN MODE] Shell commands are blocked in plan mode. "
                "Use write_file or str_replace_file with path='.plan/...' instead."
            )

        if not self._is_plan_file(path):
            raise ToolBlockedError(
                f"[PLAN MODE] Can only modify files under '.plan/' directory. Attempted: {path}"
            )

        return tool_name, tool_args


class DiffMiddleware(Middleware):
    """Capture file diffs during a turn and print them immediately after write operations."""

    _WRITE_TOOLS = frozenset({"write_file", "str_replace_file"})

    def __init__(self) -> None:
        self._old: dict[str, str] = {}

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Clear old file cache at the start of each chat."""
        self._old.clear()
        return user_message, tools

    def on_tool_call_start(self, tool_name: str, tool_args: dict) -> tuple[str, dict]:
        if tool_name in self._WRITE_TOOLS:
            path = tool_args.get("path", "")
            if path:
                try:
                    p = Path(path)
                    self._old[path] = p.read_text(encoding="utf-8") if p.exists() else ""
                except OSError:
                    self._old[path] = ""
        return tool_name, tool_args

    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        if tool_name not in self._WRITE_TOOLS:
            return result
        path = tool_args.get("path", "")
        if not path or (isinstance(result, str) and result.startswith("Error:")):
            self._old.pop(path, None)
            return result

        old = self._old.pop(path, "")
        try:
            new = Path(path).read_text(encoding="utf-8")
        except OSError:
            return result

        if old == new:
            return result

        diff = list(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        if diff:
            console.print(Syntax("\n".join(diff), "diff", theme=CODE_THEME))
        return result
