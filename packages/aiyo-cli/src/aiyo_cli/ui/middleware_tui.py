"""UI middleware components."""

from __future__ import annotations

import asyncio
import difflib
import json
import sys
from pathlib import Path
from typing import Any

from aiyo.agent.exceptions import ToolBlockedError
from aiyo.agent.middleware import Middleware
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from .theme import CODE_THEME, SPINNER_TEXT, TOOLING_TEXT, console


class TUIDisplayMiddleware(Middleware):
    """Render tool calls and file diffs in the CLI.

    auto=True  (auto mode)       — write tools run without prompting.
    auto=False (permission mode) — write tools require user confirmation before execution.
    """

    _FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file"})
    _WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file", "shell"})

    def __init__(self, auto: bool = True) -> None:
        self._call_state: dict[str, dict[str, Any]] = {}
        self._prompt_session: PromptSession[str] | None = None
        self._current_status: Any = None
        self._active_tool_calls = 0
        self.auto = auto
        self._confirm_lock = asyncio.Lock()  # serializes concurrent confirmation prompts

    def set_current_status(self, status: Any | None) -> None:
        self._current_status = status

    async def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        self._call_state.clear()
        self._active_tool_calls = 0
        return user_message, tools

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

    async def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._current_status is not None:
            self._current_status.update(SPINNER_TEXT)
            self._current_status.start()
        return messages

    async def on_llm_response(self, messages: list[dict[str, Any]], response: Any) -> Any:
        msg = response.choices[0].message
        if self._current_status is not None:
            tool_calls = msg.tool_calls or []
            if tool_calls:
                self._current_status.update(TOOLING_TEXT)
                self._current_status.start()
            else:
                self._current_status.stop()
        if msg.reasoning and msg.reasoning.content:
            console.print(f"  [muted]{msg.reasoning.content}[/muted]")
        return response

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

    async def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any], summary: str = ""
    ) -> tuple[str, str, dict[str, Any], str]:
        call_state: dict[str, Any] = {}
        name = "".join(p.capitalize() for p in tool_name.split("_"))
        prefix = f"[tool]{name}[/tool]"
        if summary:
            console.print(f"{prefix} [muted]{summary[:80]}[/muted]")
        else:
            console.print(prefix)
        self._active_tool_calls += 1

        if not self.auto and tool_name in self._WRITE_TOOL_NAMES:
            if self._current_status is not None:
                self._current_status.stop()
            confirmed = await self._ask_confirmation(tool_name)
            if not confirmed:
                self._active_tool_calls -= 1
                raise ToolBlockedError(f"Tool '{tool_name}' cancelled by user.")

        if tool_name in self._FILE_EDIT_TOOLS:
            path = tool_args.get("path", "")
            if path:
                try:
                    p = Path(path)
                    call_state["old"] = p.read_text(encoding="utf-8") if p.exists() else ""
                except OSError:
                    call_state["old"] = ""

        if call_state:
            self._call_state[tool_id] = call_state

        return tool_name, tool_id, tool_args, summary

    @staticmethod
    def _is_error(result: object) -> bool:
        """Return True if the result represents an error."""
        return isinstance(result, str) and result.startswith("Error:")

    def _ensure_prompt_session(self) -> PromptSession[str]:
        """Lazy initialization of prompt session."""
        if self._prompt_session is None:
            self._prompt_session = PromptSession()
        return self._prompt_session

    async def _ask_confirmation(self, tool_name: str) -> bool:
        """Prompt the user to confirm a write tool call. Returns True to proceed.

        Uses sys.stdin directly (via executor) instead of prompt_toolkit to avoid
        'Application is already running' errors when multiple write tools execute
        in parallel via asyncio.gather.
        """
        async with self._confirm_lock:
            console.print(
                f"  [accent][permission] Allow {tool_name}?[/accent] [muted][Y/n][/muted] ", end=""
            )
            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(None, sys.stdin.readline)
            return answer.strip().lower() in ("", "y", "yes")

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
        tool_id: str,
        tool_args: dict[str, Any],
        tool_error: Exception | None,
        result: object,
    ) -> object:
        call_state = self._call_state.pop(tool_id, {})
        label = "".join(p.capitalize() for p in tool_name.split("_"))
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

            case "todo_set":
                # Display todo list with status indicators
                todos = tool_args.get("todos", [])
                if isinstance(todos, list) and todos:
                    console.print("")
                    for todo in todos:
                        if isinstance(todo, dict):
                            status = todo.get("status", "pending")
                            title = todo.get("title", "")
                            match status:
                                case "done":
                                    icon = "[success]●[/success]"
                                    style = "muted"
                                case "in_progress":
                                    icon = "[accent]◐[/accent]"
                                    style = "heading"
                                case _:
                                    icon = "[muted]○[/muted]"
                                    style = "muted"
                            console.print(f"  {icon} [{style}]{title}[/{style}]")

            case _:
                # Default: no success footer for generic tool calls
                pass

        return result
