"""UI middleware components."""

from __future__ import annotations

import difflib
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from aiyo.agent.middleware_base import Middleware

from .theme import CODE_THEME, TOOL_SUMMARY_WIDTH, console


class ToolDisplayMiddleware(Middleware):
    """Print tool calls and file diffs to the console using Rich."""

    _FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file"})

    def __init__(
        self,
        interactive_callback: (
            Callable[[list[dict[str, Any]]], Coroutine[Any, Any, dict[str, Any]]] | None
        ) = None,
    ) -> None:
        self._old: dict[str, str] = {}
        self._prompt_session: PromptSession[str] | None = None
        self._interactive_callback = interactive_callback

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
            case "read_file" | "write_file" | "edit_file" | "read_image" | "read_pdf":
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
                # Just print tool name for other tools (task_list, think, ask_user_question, etc.)
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

    def _ensure_prompt_session(self) -> PromptSession[str]:
        """Lazy initialization of prompt session."""
        if self._prompt_session is None:
            self._prompt_session = PromptSession()
        return self._prompt_session

    async def _handle_ask_user_question(self, questions: list[dict[str, Any]]) -> dict[str, Any]:
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
            "metadata": {"source": "ask_user_question"},
        }

    async def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        if tool_name == "ask_user_question":
            # Handle interactive user questions
            questions = tool_args.get("questions", [])
            if questions:
                if self._interactive_callback is not None:
                    try:
                        result = await self._interactive_callback(questions)
                    except Exception as e:
                        console.print(f"[error]Error getting user input: {e}[/error]")
                        result = {"answers": {}, "annotations": {}, "metadata": {"error": str(e)}}
                else:
                    try:
                        result = await self._handle_ask_user_question(questions)
                    except Exception as e:
                        console.print(f"[error]Error getting user input: {e}[/error]")
                        result = {"answers": {}, "annotations": {}, "metadata": {"error": str(e)}}
            else:
                result = {"answers": {}, "annotations": {}, "metadata": {}}

        elif tool_name == "task_list":
            # Render markdown table for task list
            if isinstance(result, str):
                console.print(Markdown(result))

        elif tool_name == "think":
            # Display thought content
            thought = tool_args.get("thought", "")
            if thought:
                console.print(f"  [muted]{thought}[/muted]")

        elif tool_name == "edit_file":
            # Show full diff for edit_file
            path = tool_args.get("path", "")
            if path and not self._is_error(result):
                old = self._old.pop(path, "")
                try:
                    new = Path(path).read_text(encoding="utf-8")
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
                except OSError:
                    pass
            else:
                self._old.pop(path, None)

        elif tool_name == "write_file":
            # Show summary for write_file (too verbose to show full diff)
            path = tool_args.get("path", "")
            if path and not self._is_error(result):
                old = self._old.pop(path, "")
                try:
                    new = Path(path).read_text(encoding="utf-8")
                    if old != new:
                        old_lines = old.splitlines()
                        new_lines = new.splitlines()
                        added = len(new_lines) - len(old_lines)
                        if added > 0:
                            console.print(f"  [success]⎿  +{added} lines[/success]")
                        elif added < 0:
                            console.print(f"  [warning]⎿  {added} lines[/warning]")
                        else:
                            console.print("  [muted]⎿  modified[/muted]")
                    else:
                        console.print("  [muted]⎿  no changes[/muted]")
                except OSError:
                    pass
            else:
                self._old.pop(path, None)

        else:
            # Default: show done/failed for most tools
            if self._is_error(result):
                console.print("  [error]⎿  failed[/error]")
            else:
                console.print("  [muted]⎿  done[/muted]")

        return result
