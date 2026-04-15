"""Todo list tool — replace the whole todo list in one call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .tool_meta import tool

TodoStatus = Literal["pending", "in_progress", "done"]


@dataclass
class TodoItem:
    """A single todo item."""

    title: str
    status: TodoStatus


def _todo_set_summary(tool_args: dict[str, object]) -> str:
    todos = tool_args.get("todos", [])
    if not isinstance(todos, list) or not todos:
        return ""
    done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "done")
    in_progress = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "in_progress")
    summary = f"{len(todos)} item(s)"
    status_parts: list[str] = []
    if in_progress:
        status_parts.append(f"{in_progress} in progress")
    if done:
        status_parts.append(f"{done} done")
    if status_parts:
        summary = f"{summary} ({', '.join(status_parts)})"
    return summary


@tool(summary=_todo_set_summary)
async def todo_set(todos: list[TodoItem]) -> str:
    """Update the todo list by replacing it entirely with the provided items.

    Use this tool to track progress on multi-step tasks. Call it at the start
    of a complex task to lay out the plan, then call it again whenever a step
    changes status. Always pass the complete list — items omitted from the call
    will disappear from the list.

    Status lifecycle:
      pending → in_progress → done

    Keep the list short and focused: 3–7 items is ideal. Each title should be
    a short, action-oriented phrase (e.g. "Read config file", "Write unit tests").

    Args:
        todos: The complete, up-to-date todo list. Each TodoItem has:
            - title (str): Short label for the task.
            - status (str): One of "pending", "in_progress", or "done".

    Returns:
        Confirmation that the todo list was updated.
    """
    return "Todo list updated."
