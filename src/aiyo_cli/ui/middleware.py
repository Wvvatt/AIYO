"""UI middleware components."""

from __future__ import annotations

import asyncio
import difflib
import json
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from aiyo.agent.middleware_base import Middleware

from .theme import CODE_THEME, SPINNER_TEXT, TOOL_SUMMARY_WIDTH, TOOLING_TEXT, console


class ToolDisplayMiddleware(Middleware):
    """Print tool calls and file diffs to the console using Rich."""

    _FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file"})

    def __init__(self) -> None:
        self._call_state: dict[str, dict[str, Any]] = {}
        self._prompt_session: PromptSession[str] | None = None
        self._current_status: Any = None
        self._active_tool_calls = 0

    def set_current_status(self, status: Any | None) -> None:
        self._current_status = status

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        self._call_state.clear()
        self._active_tool_calls = 0
        return user_message, tools

    @staticmethod
    def _format_name(tool_name: str) -> str:
        return "".join(p.capitalize() for p in tool_name.split("_"))

    @staticmethod
    def _parse_tool_raw_args(tool_args: dict[str, Any]) -> dict[str, Any]:
        raw = tool_args.get("args") or {}
        if isinstance(raw, str):
            import json as _json

            try:
                parsed = _json.loads(raw)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _read_file_text(path: str, label: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            console.print(f"  [muted]⎿  {label}: unable to read file[/muted]")
            return None

    def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._current_status is not None:
            self._current_status.update(SPINNER_TEXT)
            self._current_status.start()
        return messages

    def on_llm_response(self, messages: list[dict[str, Any]], response: Any) -> Any:
        if self._current_status is not None:
            tool_calls = response.choices[0].message.tool_calls or []
            if tool_calls:
                self._current_status.update(TOOLING_TEXT)
                self._current_status.start()
            else:
                self._current_status.stop()
        return response

    def _tool_summary(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """Build a one-line summary for tool display."""
        name = self._format_name(tool_name)
        prefix = f"[tool]{name}[/tool]"

        match tool_name:
            case "task_create":
                tasks = tool_args.get("tasks", [])
                if isinstance(tasks, list) and tasks:
                    title = str(tasks[0].get("title", ""))
                    summary = f"{len(tasks)} task(s)"
                    if title:
                        summary = f"{summary}: {title}"
                    return f"{prefix} [muted]{summary[:TOOL_SUMMARY_WIDTH]}[/muted]"
                return prefix
            case "task_get" | "task_delete" | "task_update":
                task_id = tool_args.get("task_id", "")
                return f"{prefix} [muted]{task_id}[/muted]"
            case "read_file" | "write_file" | "edit_file" | "read_image" | "read_pdf":
                summary = tool_args.get("path", "")
                return f"{prefix} [muted]{summary}[/muted]"
            case "grep_files":
                pattern = tool_args.get("pattern", "")
                path = tool_args.get("path", ".")
                summary = f"{pattern!r} in {path}"
                return f"{prefix} [muted]{summary[:TOOL_SUMMARY_WIDTH]}[/muted]"
            case "glob_files":
                summary = tool_args.get("pattern", "")
                return f"{prefix} [muted]{summary}[/muted]"
            case "list_directory":
                summary = tool_args.get("path", ".")
                return f"{prefix} [muted]{summary}[/muted]"
            case "shell":
                cmd = tool_args.get("command", "")
                return f"{prefix} [muted]{cmd[:TOOL_SUMMARY_WIDTH]}[/muted]"
            case "fetch_url":
                summary = tool_args.get("url", "")
                return f"{prefix} [muted]{summary[:TOOL_SUMMARY_WIDTH]}[/muted]"
            case "load_skill":
                summary = tool_args.get("name", "")
                return f"{prefix} [muted]{summary}[/muted]"
            case "load_skill_resource":
                skill = tool_args.get("skill_name", "")
                resource = tool_args.get("resource_path", "")
                summary = f"{skill}/{resource}"
                return f"{prefix} [muted]{summary}[/muted]"
            case "jira_cli":
                raw = self._parse_tool_raw_args(tool_args)
                identity = raw.get("issue_key", "")
                cmd = tool_args.get("command", "")
                suffix = f" {identity}" if identity else ""
                return f"{prefix} [muted]{cmd}{suffix}[/muted]"
            case "confluence_cli":
                raw = self._parse_tool_raw_args(tool_args)
                identity = raw.get("page_id", "")
                cmd = tool_args.get("command", "")
                suffix = f" {identity}" if identity else ""
                return f"{prefix} [muted]{cmd}{suffix}[/muted]"
            case "gerrit_cli":
                raw = self._parse_tool_raw_args(tool_args)
                identity = raw.get("change_id", "")
                cmd = tool_args.get("command", "")
                suffix = f" {identity}" if identity else ""
                return f"{prefix} [muted]{cmd}{suffix}[/muted]"
            case _:
                return prefix

    @staticmethod
    def _render_task_result(result: dict[str, Any]) -> str:
        """Render structured task tool results for interactive display."""
        action = result.get("action")
        if action == "list":
            tasks = result.get("tasks", [])
            if not tasks:
                return "No tasks found."

            lines = [
                "| ID | Status | Priority | Title | Tags |",
                "|----|--------|----------|-------|------|",
            ]
            for task in tasks:
                tags = " ".join(f"`{tag}`" for tag in task.get("tags", [])) or "-"
                lines.append(
                    f"| `{task.get('id', '')}` | {task.get('status', '')} | "
                    f"{task.get('priority', '')} | {task.get('title', '')} | {tags} |"
                )
            lines.append("")
            lines.append(f"**Total: {result.get('total', len(tasks))} task(s)**")
            return "\n".join(lines)

        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except TypeError:
            return str(result)

    def on_tool_call_start(
        self, tool_name: str, _tool_id: str, tool_args: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        call_state: dict[str, Any] = {}
        console.print(self._tool_summary(tool_name, tool_args))
        self._active_tool_calls += 1

        if tool_name in self._FILE_EDIT_TOOLS:
            path = tool_args.get("path", "")
            if path:
                try:
                    p = Path(path)
                    call_state["old"] = p.read_text(encoding="utf-8") if p.exists() else ""
                except OSError:
                    call_state["old"] = ""

        if call_state:
            self._call_state[_tool_id] = call_state

        return tool_name, _tool_id, tool_args

    @staticmethod
    def _is_error(result: object) -> bool:
        """Return True if the result represents an error."""
        return isinstance(result, str) and result.startswith("Error:")

    def _ensure_prompt_session(self) -> PromptSession[str]:
        """Lazy initialization of prompt session."""
        if self._prompt_session is None:
            self._prompt_session = PromptSession()
        return self._prompt_session

    async def _handle_ask_user(self, questions: list[dict[str, Any]]) -> dict[str, Any]:
        """Display questions and collect user answers using inline prompts.

        Args:
            questions: List of question definitions.

        Returns:
            Dictionary with answers, annotations, and metadata.
        """
        answers: dict[str, str] = {}
        annotations: dict[str, dict[str, Any]] = {}
        prompt_session = self._ensure_prompt_session()

        for idx, q in enumerate(questions, 1):
            question_text = q.get("question", "")
            header = q.get("header", "")
            options = q.get("options", [])
            multi_select = q.get("multi_select", False)

            # Display question header
            header_str = f" [{header}]" if header else ""
            console.print(f"\n[accent]Question {idx}/{len(questions)}:{header_str}[/accent]")
            console.print(Panel(Markdown(question_text), border_style="muted"))

            if not options:
                # Open-ended question
                with patch_stdout():
                    answer = await prompt_session.prompt_async("Your answer: ")
                answers[question_text] = answer.strip()
                continue

            # Display options as a numbered list
            console.print("\n[muted]Options:[/muted]")
            for opt_idx, opt in enumerate(options, 1):
                label = opt.get("label", "")
                description = opt.get("description", "")
                if description:
                    console.print(
                        f"  [accent]{opt_idx}.[/accent] [heading]{label}[/heading] - "
                        f"[muted]{description}[/muted]"
                    )
                else:
                    console.print(f"  [accent]{opt_idx}.[/accent] [heading]{label}[/heading]")

            # Handle multi-select
            if multi_select:
                console.print("\n[muted](Select multiple options, separated by commas)[/muted]")

            with patch_stdout():
                prompt_text = (
                    "Select options (e.g., 1,3): " if multi_select else "Your choice (number): "
                )
                answer = await prompt_session.prompt_async(prompt_text)

            answer = answer.strip()

            # Parse answer
            if multi_select:
                # Parse comma-separated selections
                selected_indices = [
                    int(x.strip()) - 1 for x in answer.split(",") if x.strip().isdigit()
                ]
                selected_labels = [
                    options[i].get("label", "") for i in selected_indices if 0 <= i < len(options)
                ]
                # Handle "Other" selection
                if "other" in answer.lower():
                    with patch_stdout():
                        other_answer = await prompt_session.prompt_async("Please specify (Other): ")
                    selected_labels.append(f"Other: {other_answer.strip()}")
                answers[question_text] = ", ".join(selected_labels) if selected_labels else answer
            else:
                # Single selection
                if answer.isdigit():
                    opt_idx = int(answer) - 1
                    if 0 <= opt_idx < len(options):
                        answers[question_text] = options[opt_idx].get("label", answer)
                    else:
                        answers[question_text] = answer
                elif answer.lower() == "other":
                    with patch_stdout():
                        other_answer = await prompt_session.prompt_async("Please specify (Other): ")
                    answers[question_text] = f"Other: {other_answer.strip()}"
                else:
                    answers[question_text] = answer

            # Store annotations if any
            selected_labels = (
                answers.get(question_text, "").split(", ")
                if multi_select
                else [answers.get(question_text, "")]
            )
            for selected_label in selected_labels:
                selected_option = next(
                    (opt for opt in options if opt.get("label") == selected_label),
                    None,
                )
                if selected_option and ("preview" in selected_option or "notes" in selected_option):
                    annotations[question_text] = {
                        "preview": selected_option.get("preview"),
                        "notes": None,
                    }

        return {
            "answers": answers,
            "annotations": annotations,
            "metadata": {"source": "ask_user"},
        }

    async def on_tool_call_end(
        self,
        tool_name: str,
        _tool_id: str,
        tool_args: dict[str, Any],
        tool_error: Exception | None,
        result: object,
    ) -> object:
        call_state = self._call_state.pop(_tool_id, {})
        label = self._format_name(tool_name)
        failed = tool_error is not None or self._is_error(result)

        if self._active_tool_calls > 0:
            self._active_tool_calls -= 1
        if self._current_status is not None and self._active_tool_calls == 0:
            self._current_status.stop()

        if failed:
            console.print(f"  [error]⎿  {label}: failed[/error]")
            return result

        match tool_name:
            case "ask_user":
                # Handle interactive user questions
                questions = tool_args.get("questions", [])
                if questions:
                    try:
                        result = await self._handle_ask_user(questions)
                    except Exception as e:
                        console.print(f"[error]Error getting user input: {e}[/error]")
                        result = {
                            "answers": {},
                            "annotations": {},
                            "metadata": {"error": str(e)},
                        }
                else:
                    result = {"answers": {}, "annotations": {}, "metadata": {}}

            case "task_list":
                if isinstance(result, dict):
                    console.print(Markdown(self._render_task_result(result)))

            case "think":
                # Display thought content
                thought = tool_args.get("thought", "")
                if thought:
                    console.print(f"  [muted]{thought}[/muted]")

            case "edit_file":
                # Show full diff for edit_file
                path = tool_args.get("path", "")
                if path:
                    old = call_state.get("old", "")
                    new = self._read_file_text(path, label)
                    if new is not None:
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
                                console.print(f"  [muted]⎿  {label}: no visible diff[/muted]")
                        else:
                            console.print(f"  [muted]⎿  {label}: no changes[/muted]")

            case "write_file":
                # Show summary for write_file (too verbose to show full diff)
                path = tool_args.get("path", "")
                if path:
                    old = call_state.get("old", "")
                    new = self._read_file_text(path, label)
                    if new is not None:
                        if old != new:
                            old_lines = old.splitlines()
                            new_lines = new.splitlines()
                            added = len(new_lines) - len(old_lines)
                            if added > 0:
                                console.print(f"  [success]⎿  {label}: +{added} lines[/success]")
                            elif added < 0:
                                console.print(f"  [warning]⎿  {label}: {added} lines[/warning]")
                            else:
                                console.print(f"  [muted]⎿  {label}: modified[/muted]")
                        else:
                            console.print(f"  [muted]⎿  {label}: no changes[/muted]")

            case _:
                # Default: no success footer for generic tool calls
                pass

        return result
