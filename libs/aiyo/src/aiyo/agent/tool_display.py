"""Tool display utilities.

Provides functions for generating human-readable summaries for tool calls.
"""

from typing import Any


def create_tool_summary(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Create a human-readable summary for a tool call.

    Args:
        tool_name: The name of the tool being called.
        tool_args: The arguments passed to the tool.

    Returns:
        A short human-readable summary string (without tool name prefix).
    """
    match tool_name:
        case "read_file" | "write_file" | "edit_file" | "read_image" | "read_pdf":
            return tool_args.get("path", "")

        case "list_directory":
            return tool_args.get("path", ".")

        case "glob_files":
            return tool_args.get("pattern", "")

        case "grep_files":
            pattern = tool_args.get("pattern", "")
            path = tool_args.get("path", ".")
            return f"{pattern!r} in {path}"

        case "shell":
            return tool_args.get("command", "")[:80]

        case "fetch_url":
            return tool_args.get("url", "")

        case "load_skill":
            return tool_args.get("name", "")

        case "load_skill_resource":
            skill = tool_args.get("skill_name", "")
            resource = tool_args.get("resource_path", "")
            return f"{skill}/{resource}"

        case "think":
            return tool_args.get("thought", "")[:80]

        case "ask_user":
            questions = tool_args.get("questions", [])
            if questions:
                first = questions[0]
                if isinstance(first, dict):
                    return first.get("question", "")[:80]
                return str(first)[:80]
            return ""

        case "task_create":
            tasks = tool_args.get("tasks", [])
            if isinstance(tasks, list) and tasks:
                title = str(tasks[0].get("title", ""))
                summary = f"{len(tasks)} task(s)"
                if title:
                    summary = f"{summary}: {title}"
                return summary[:80]
            return ""

        case "task_get" | "task_delete" | "task_update":
            return tool_args.get("task_id", "")

        case "todo_set":
            todos = tool_args.get("todos", [])
            if isinstance(todos, list) and todos:
                total = len(todos)
                done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "done")
                in_progress = sum(
                    1 for t in todos if isinstance(t, dict) and t.get("status") == "in_progress"
                )
                summary = f"{total} item(s)"
                if done > 0 or in_progress > 0:
                    status_parts = []
                    if in_progress > 0:
                        status_parts.append(f"{in_progress} in progress")
                    if done > 0:
                        status_parts.append(f"{done} done")
                    summary = f"{summary} ({', '.join(status_parts)})"
                return summary
            return ""

        case _:
            return ""
