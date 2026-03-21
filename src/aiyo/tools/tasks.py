"""Task management tool - CRUD operations for tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import ToolError

# Sentinel object to detect unset optional arguments
_UNSET = object()


@dataclass
class Task:
    """A single task with metadata."""

    id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending, in_progress, completed
    priority: str = "medium"  # critical, urgent, high, medium, low
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """Create task from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            priority=data.get("priority", "medium"),
            tags=data.get("tags", []),
        )


class _TaskManager:
    """In-memory task manager with CRUD operations."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._counter = 0

    def _generate_id(self) -> str:
        """Generate a unique task ID."""
        self._counter += 1
        return f"task_{self._counter:04d}"

    def create(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        tags: list[str] | None = None,
    ) -> Task:
        """Create a new task.

        Args:
            title: Task title (required).
            description: Task description (optional).
            priority: Task priority - critical, urgent, high, medium, low (default: medium).
            tags: List of tag strings (optional).

        Returns:
            The created Task object.

        Raises:
            ToolError: If title is empty, priority is invalid, or task limit reached.
        """
        if len(self._tasks) >= 20:
            raise ToolError(
                "Task limit reached (max 20 tasks). Delete some tasks before creating new ones."
            )

        if not title or not title.strip():
            raise ToolError("Task title is required and cannot be empty.")

        priority = priority.lower()
        if priority not in ("critical", "urgent", "high", "medium", "low"):
            raise ToolError(
                f"Invalid priority '{priority}'. Must be one of: critical, urgent, high, medium, low."
            )

        task = Task(
            id=self._generate_id(),
            title=title.strip(),
            description=description.strip(),
            status="pending",
            priority=priority,
            tags=tags or [],
        )
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task:
        """Get a task by ID.

        Args:
            task_id: The task ID.

        Returns:
            The Task object.

        Raises:
            ToolError: If task not found.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ToolError(f"Task '{task_id}' not found.")
        return task

    def update(
        self,
        task_id: str,
        title: Any = _UNSET,
        description: Any = _UNSET,
        status: Any = _UNSET,
        priority: Any = _UNSET,
        tags: list[str] = _UNSET,  # type: ignore[assignment]
    ) -> Task:
        """Update an existing task.

        Args:
            task_id: The task ID.
            title: New title (optional).
            description: New description (optional).
            status: New status - pending, in_progress, completed (optional).
            priority: New priority - critical, urgent, high, medium, low (optional).
            tags: New tags list (optional).

        Returns:
            The updated Task object.

        Raises:
            ToolError: If task not found or invalid values provided.
        """
        task = self.get(task_id)

        if title is not _UNSET:
            if not title.strip():
                raise ToolError("Task title cannot be empty.")
            task.title = title.strip()

        if description is not _UNSET:
            task.description = description.strip()

        if status is not _UNSET:
            status = status.lower()
            if status not in ("pending", "in_progress", "completed"):
                raise ToolError(
                    f"Invalid status '{status}'. Must be one of: pending, in_progress, completed."
                )
            # Check if another task is already in_progress
            if status == "in_progress":
                for other_task in self._tasks.values():
                    if other_task.id != task_id and other_task.status == "in_progress":
                        raise ToolError(
                            f"Cannot start this task. Task '{other_task.id}' is already in progress. "
                            "Complete or pause the current task before starting a new one."
                        )
            task.status = status

        if priority is not _UNSET:
            priority = priority.lower()
            if priority not in ("critical", "urgent", "high", "medium", "low"):
                raise ToolError(
                    f"Invalid priority '{priority}'. Must be one of: critical, urgent, high, medium, low."
                )
            task.priority = priority

        if tags is not _UNSET:
            task.tags = tags

        return task

    def delete(self, task_id: str) -> None:
        """Delete a task.

        Args:
            task_id: The task ID to delete.

        Raises:
            ToolError: If task not found.
        """
        if task_id not in self._tasks:
            raise ToolError(f"Task '{task_id}' not found.")
        del self._tasks[task_id]

    def list(
        self,
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Tasks are sorted by priority first (critical > urgent > high > medium > low),
        then by task ID (creation order) within the same priority.

        Args:
            status: Filter by status (optional).
            priority: Filter by priority (optional).
            tag: Filter by tag (optional).

        Returns:
            List of Task objects matching the filters.
        """
        tasks = list(self._tasks.values())

        # Apply filters
        if status:
            tasks = [t for t in tasks if t.status == status.lower()]
        if priority:
            tasks = [t for t in tasks if t.priority == priority.lower()]
        if tag:
            tag = tag.lower()
            tasks = [t for t in tasks if tag in [t.lower() for t in t.tags]]

        # Sort by priority first, then by task ID
        priority_order = {"critical": 0, "urgent": 1, "high": 2, "medium": 3, "low": 4}
        tasks.sort(key=lambda t: (priority_order.get(t.priority, 99), t.id))

        return tasks

    def clear(self) -> None:
        """Clear all tasks."""
        self._tasks.clear()
        self._counter = 0

    def count(self) -> int:
        """Return total number of tasks."""
        return len(self._tasks)


# Global task manager instance
_TASK_MANAGER = _TaskManager()


def _format_status(status: str) -> str:
    """Format status with icon."""
    return {
        "pending": "[ ]",
        "in_progress": "[>]",
        "completed": "[x]",
    }.get(status, "[?]")


def _format_priority(priority: str) -> str:
    """Format priority with visual indicator."""
    return {
        "critical": "!!!!",
        "urgent": "!!!",
        "high": "!!",
        "medium": "!",
        "low": "",
    }.get(priority, "")


def _format_task(task: Task) -> str:
    """Format a single task for display in one line."""
    status = _format_status(task.status)
    priority = _format_priority(task.priority)

    parts = [f"{status} {task.id}: {priority}{task.title}"]
    if task.description:
        parts.append(f"| {task.description}")
    if task.tags:
        parts.append(f"#{' '.join(task.tags)}")

    return " ".join(parts)


def _format_task_list(tasks: list[Task]) -> str:
    """Format a list of tasks as a markdown table."""
    if not tasks:
        return "No tasks found."

    lines = []
    lines.append("| Status | ID | Priority | Title | Tags |")
    lines.append("|--------|------|----------|-------|------|")

    for task in tasks:
        status = _format_status(task.status)
        priority = _format_priority(task.priority)
        tags = " ".join(f"`{t}`" for t in task.tags) if task.tags else "-"
        lines.append(f"| {status} | `{task.id}` | {priority} | {task.title} | {tags} |")

    lines.append("")
    lines.append(f"**Total: {len(tasks)} task(s)**")
    return "\n".join(lines)


async def task_create(
    title: str,
    description: str = "",
    priority: str = "medium",
    tags: list[str] | None = None,
) -> str:
    """Create a new task.

    Args:
        title: Task title (required, max 200 chars).
        description: Task description (optional).
        priority: Priority level - critical, urgent, high, medium, low (default: medium).
        tags: List of tags for categorization (optional).

    Returns:
        Formatted string with created task details.

    Raises:
        ToolError: If title is empty or parameters are invalid.
    """
    task = _TASK_MANAGER.create(
        title=title,
        description=description,
        priority=priority,
        tags=tags or [],
    )
    return f"Task created successfully:\n\n{_format_task(task)}"


async def task_get(task_id: str) -> str:
    """Get a task by its ID.

    Args:
        task_id: The unique task identifier (e.g., 'task_0001').

    Returns:
        Formatted string with full task details.

    Raises:
        ToolError: If task not found.
    """
    task = _TASK_MANAGER.get(task_id)
    return _format_task(task)


async def task_update(
    task_id: str,
    title: str = "",
    description: str = "",
    status: str = "",
    priority: str = "",
    tags: list[str] = _UNSET,  # type: ignore[assignment]
) -> str:
    """Update an existing task.

    Only provided fields will be updated. Omit fields to keep current values.

    Args:
        task_id: The task ID to update.
        title: New title (optional).
        description: New description (optional).
        status: New status - pending, in_progress, completed, cancelled (optional).
        priority: New priority - critical, urgent, high, medium, low (optional).
        tags: New tags list (optional).

    Returns:
        Formatted string with updated task details.

    Raises:
        ToolError: If task not found or invalid values provided.
    """
    # Build update dict with only provided values
    kwargs: dict[str, Any] = {}
    if title:
        kwargs["title"] = title
    if description:
        kwargs["description"] = description
    if status:
        kwargs["status"] = status
    if priority:
        kwargs["priority"] = priority
    if tags is not _UNSET:
        kwargs["tags"] = tags

    if not kwargs:
        raise ToolError("No fields provided to update. Specify at least one field.")

    task = _TASK_MANAGER.update(task_id, **kwargs)
    return f"Task updated successfully:\n\n{_format_task(task)}"


async def task_list(
    status: str = "",
    priority: str = "",
    tag: str = "",
) -> str:
    """List tasks with optional filtering.

    Tasks are always returned in creation order (by task ID).

    Args:
        status: Filter by status - pending, in_progress, completed (optional).
        priority: Filter by priority - critical, urgent, high, medium, low (optional).
        tag: Filter by tag name (optional).

    Returns:
        Formatted list of tasks.
    """
    tasks = _TASK_MANAGER.list(
        status=status if status else None,
        priority=priority if priority else None,
        tag=tag if tag else None,
    )
    return _format_task_list(tasks)


async def task_delete(task_id: str) -> str:
    """Delete a task permanently.

    Args:
        task_id: The task ID to delete.

    Returns:
        Success message.

    Raises:
        ToolError: If task not found.
    """
    _TASK_MANAGER.delete(task_id)
    return f"Task '{task_id}' deleted successfully."
