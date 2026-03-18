"""UI middleware components."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from rich.syntax import Syntax

from aiyo import Middleware

from .theme import CODE_THEME, TOOL_SUMMARY_WIDTH, console


class ToolDisplayMiddleware(Middleware):
    """Print tool calls and file diffs to the console using Rich."""

    _FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file"})
    _SILENT_TOOLS = frozenset({"task_list", "think"})  # Tools that don't show done/failed indicator

    def __init__(self) -> None:
        self._old: dict[str, str] = {}

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        self._old.clear()
        return user_message, tools

    def on_tool_call_start(self, tool_name: str, tool_args: dict) -> tuple[str, dict]:
        name = "".join(p.capitalize() for p in tool_name.split("_"))
        match tool_name:
            case "task_create":
                title = tool_args.get("title", "")
                console.print(f"[tool]{name}[/tool] [muted]{title[:TOOL_SUMMARY_WIDTH]}[/muted]")
            case "task_get" | "task_delete":
                task_id = tool_args.get("task_id", "")
                console.print(f"[tool]{name}[/tool] [muted]{task_id}[/muted]")
            case "task_update":
                task_id = tool_args.get("task_id", "")
                console.print(f"[tool]{name}[/tool] [muted]{task_id}[/muted]")
            case "task_list":
                pass  # task_list result shown in on_tool_call_end
            case "think":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('thought', '')}[/muted]")
            case "read_file" | "write_file" | "edit_file":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('path', '')}[/muted]")
            case "grep_files":
                pattern = tool_args.get("pattern", "")
                path = tool_args.get("path", ".")
                summary = f"{pattern!r} in {path}"
                console.print(f"[tool]{name}[/tool] [muted]{summary[:TOOL_SUMMARY_WIDTH]}[/muted]")
            case "glob_files":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('pattern', '')}[/muted]")
            case "list_directory":
                console.print(
                    f"[tool]{name}[/tool] [muted]{tool_args.get('relative_path', '.')}[/muted]"
                )
            case "shell":
                cmd = tool_args.get("command", "")
                console.print(f"[tool]{name}[/tool] [muted]{cmd[:TOOL_SUMMARY_WIDTH]}[/muted]")
            case "load_skill":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('name', '')}[/muted]")
            case "load_skill_resource":
                skill = tool_args.get("skill_name", "")
                resource = tool_args.get("resource_path", "")
                console.print(f"[tool]{name}[/tool] [muted]{skill}/{resource}[/muted]")
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

        if tool_name in self._FILE_EDIT_TOOLS:
            path = tool_args.get("path", "")
            if path:
                try:
                    p = Path(path)
                    self._old[path] = p.read_text(encoding="utf-8") if p.exists() else ""
                except OSError:
                    self._old[path] = ""

        return tool_name, tool_args

    @staticmethod
    def _is_error(result: object) -> bool:
        """Return True if the result represents an error."""
        return isinstance(result, str) and result.startswith("Error:")

    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        if tool_name == "task_list":
            name = "".join(p.capitalize() for p in tool_name.split("_"))
            console.print(f"[tool]{name}[/tool]")
            if isinstance(result, str):
                # Render markdown table for task list
                from rich.markdown import Markdown

                console.print(Markdown(result))

        if tool_name in self._FILE_EDIT_TOOLS:
            path = tool_args.get("path", "")
            if path and not self._is_error(result):
                old = self._old.pop(path, "")
                try:
                    new = Path(path).read_text(encoding="utf-8")
                except OSError:
                    return result
                if old != new:
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
                        diff_text = "\n".join(diff)
                        console.print(Syntax(diff_text, "diff", theme=CODE_THEME))
            else:
                self._old.pop(path, None)
        elif tool_name not in self._SILENT_TOOLS:
            if self._is_error(result):
                console.print("  [error]⎿  failed[/error]")
            else:
                console.print("  [muted]⎿  done[/muted]")

        return result
