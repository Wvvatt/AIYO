"""Task management tool - CRUD operations for tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from .exceptions import ToolError

# Sentinel object to detect unset optional arguments
_UNSET = object()

TaskStatus = Literal["pending", "in_progress", "completed"]
TaskPriority = Literal["critical", "urgent", "high", "medium", "low"]


@dataclass
class Task:
    """A single task with metadata."""

    id: str
    title: str
    description: str = ""
    status: TaskStatus = "pending"
    priority: TaskPriority = "medium"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
        self._lock = asyncio.Lock()

    def _generate_id(self) -> str:
        """Generate a unique task ID."""
        self._counter += 1
        return f"task_{self._counter:04d}"

    def _get_unlocked(self, task_id: str) -> Task:
        """Get a task by ID without acquiring lock."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ToolError(f"Task '{task_id}' not found.")
        return task

    @staticmethod
    def _normalize_priority(priority: str) -> TaskPriority:
        """Validate and normalize a priority value."""
        normalized = priority.lower()
        if normalized not in ("critical", "urgent", "high", "medium", "low"):
            raise ToolError(
                f"Invalid priority '{priority}'. Must be one of: critical, urgent, high, medium, low."
            )
        return normalized

    def _create_unlocked(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        tags: list[str] | None = None,
    ) -> Task:
        """Create a task without acquiring the lock."""
        if len(self._tasks) >= 20:
            raise ToolError(
                "Task limit reached (max 20 tasks). Delete some tasks before creating new ones."
            )

        if not title or not title.strip():
            raise ToolError("Task title is required and cannot be empty.")

        task = Task(
            id=self._generate_id(),
            title=title.strip(),
            description=description.strip(),
            status="pending",
            priority=self._normalize_priority(priority),
            tags=tags or [],
        )
        self._tasks[task.id] = task
        return task

    async def create(
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
        async with self._lock:
            return self._create_unlocked(title, description, priority, tags)

    async def create_many(self, items: list[dict[str, Any]]) -> list[Task]:
        """Create multiple tasks atomically."""
        async with self._lock:
            if not items:
                raise ToolError("tasks must contain at least one item.")
            if len(self._tasks) + len(items) > 20:
                raise ToolError(
                    "Task limit reached (max 20 tasks). Delete some tasks before creating new ones."
                )

            created: list[Task] = []
            for item in items:
                if not isinstance(item, dict):
                    raise ToolError("Each task item must be an object.")
                created.append(
                    self._create_unlocked(
                        title=str(item.get("title", "")),
                        description=str(item.get("description", "")),
                        priority=str(item.get("priority", "medium")),
                        tags=item.get("tags") or [],
                    )
                )
            return created

    async def get(self, task_id: str) -> Task:
        """Get a task by ID.

        Args:
            task_id: The task ID.

        Returns:
            The Task object.

        Raises:
            ToolError: If task not found.
        """
        async with self._lock:
            return self._get_unlocked(task_id)

    async def update(
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
        async with self._lock:
            task = self._get_unlocked(task_id)

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

    async def delete(self, task_id: str) -> None:
        """Delete a task.

        Args:
            task_id: The task ID to delete.

        Raises:
            ToolError: If task not found.
        """
        async with self._lock:
            if task_id not in self._tasks:
                raise ToolError(f"Task '{task_id}' not found.")
            del self._tasks[task_id]

    async def list(
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
        async with self._lock:
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


def _task_response(action: str, task: Task) -> dict[str, Any]:
    """Build a structured response for single-task operations."""
    return {
        "ok": True,
        "action": action,
        "task": task.to_dict(),
    }


async def task_create(
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a new task.

    Args:
        tasks: Batch input. Each item may include title, description, priority,
            and tags.

    Returns:
        Structured result containing the created tasks.

    Raises:
        ToolError: If any task is invalid or parameters are missing.
    """
    created = await _TASK_MANAGER.create_many(tasks)
    response = {
        "ok": True,
        "action": "create",
        "tasks": [task.to_dict() for task in created],
        "total": len(created),
    }
    if len(created) == 1:
        response["task"] = created[0].to_dict()
    return response


async def task_get(task_id: str) -> dict[str, Any]:
    """Get a task by its ID.

    Args:
        task_id: The unique task identifier (e.g., 'task_0001').

    Returns:
        Structured result containing the task.

    Raises:
        ToolError: If task not found.
    """
    task = await _TASK_MANAGER.get(task_id)
    return _task_response("get", task)


async def task_update(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing task.

    Only provided fields will be updated. Use an empty string or empty list to
    explicitly clear description or tags. Omit a field by passing null.

    Args:
        task_id: The task ID to update.
        title: New title. Pass null to leave unchanged.
        description: New description. Pass "" to clear, null to leave unchanged.
        status: New status: pending, in_progress, or completed.
        priority: New priority: critical, urgent, high, medium, or low.
        tags: New tags list. Pass [] to clear, null to leave unchanged.

    Returns:
        Structured result containing the updated task.

    Raises:
        ToolError: If task not found or invalid values provided.
    """
    # Build update dict with only provided values
    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    if tags is not None:
        kwargs["tags"] = tags

    if not kwargs:
        raise ToolError(
            "No fields provided to update. Set at least one of: title, description, status, priority, tags."
        )

    task = await _TASK_MANAGER.update(task_id, **kwargs)
    return _task_response("update", task)


async def task_list(
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """List tasks with optional filtering.

    Tasks are sorted by priority first, then by task ID within the same priority.

    Args:
        status: Filter by status: pending, in_progress, or completed.
        priority: Filter by priority: critical, urgent, high, medium, or low.
        tag: Filter by tag name.

    Returns:
        Structured result containing all matching tasks and applied filters.
    """
    tasks = await _TASK_MANAGER.list(status=status, priority=priority, tag=tag)
    return {
        "ok": True,
        "action": "list",
        "tasks": [task.to_dict() for task in tasks],
        "total": len(tasks),
        "filters": {
            "status": status,
            "priority": priority,
            "tag": tag,
        },
        "sort": "priority_then_id",
    }


async def task_delete(task_id: str) -> dict[str, Any]:
    """Delete a task permanently.

    Args:
        task_id: The task ID to delete.

    Returns:
        Structured result indicating the deleted task ID.

    Raises:
        ToolError: If task not found.
    """
    await _TASK_MANAGER.delete(task_id)
    return {
        "ok": True,
        "action": "delete",
        "task_id": task_id,
    }
