"""Task management tool - CRUD operations for tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from .exceptions import ToolError

# Sentinel object to detect unset optional arguments
_UNSET = object()

TaskStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class Task:
    """A single task with metadata."""

    id: str
    title: str
    description: str = ""
    status: TaskStatus = "pending"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
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

    def _create_unlocked(
        self,
        title: str,
        description: str = "",
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
            tags=tags or [],
        )
        self._tasks[task.id] = task
        return task

    async def create(
        self,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Task:
        """Create a new task.

        Args:
            title: Task title (required).
            description: Task description (optional).
            tags: List of tag strings (optional).

        Returns:
            The created Task object.

        Raises:
            ToolError: If title is empty or task limit reached.
        """
        async with self._lock:
            return self._create_unlocked(title, description, tags)

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
        tags: list[str] = _UNSET,  # type: ignore[assignment]
    ) -> Task:
        """Update an existing task.

        Args:
            task_id: The task ID.
            title: New title (optional).
            description: New description (optional).
            status: New status - pending, in_progress, completed (optional).
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
        tag: str | None = None,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Args:
            status: Filter by status (optional).
            tag: Filter by tag (optional).

        Returns:
            List of Task objects matching the filters.
        """
        async with self._lock:
            tasks = list(self._tasks.values())

            # Apply filters
            if status:
                tasks = [t for t in tasks if t.status == status.lower()]
            if tag:
                tag = tag.lower()
                tasks = [t for t in tasks if tag in [t.lower() for t in t.tags]]

            tasks.sort(key=lambda t: t.id)

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
    """Create one or more tasks to track work that needs to be done.

    Use this tool to break down a goal into concrete, actionable steps. Each task
    has a title, optional description, optional tags, and starts in "pending" status.
    Tasks are assigned sequential IDs (task_0001, task_0002, ...) in creation order.

    Up to 20 tasks can exist at once. Create multiple tasks in a single call when
    you know the full list of work upfront — this is more efficient than creating
    them one by one.

    Args:
        tasks: List of task objects to create. Each object supports:
            - title (required): Short, actionable label for the task.
            - description (optional): Detailed explanation of what needs to be done.
            - tags (optional): List of label strings for grouping or filtering.

    Returns:
        Structured result containing the created tasks and their assigned IDs.

    Raises:
        ToolError: If title is missing/empty, or the 20-task limit would be exceeded.
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
    """Retrieve a single task by its ID to check its current state.

    Use this when you need the full details of a specific task — its title,
    description, status, and tags — without listing all tasks.

    Args:
        task_id: The unique task identifier assigned at creation (e.g., 'task_0001').

    Returns:
        Structured result containing the full task object.

    Raises:
        ToolError: If no task with the given ID exists.
    """
    task = await _TASK_MANAGER.get(task_id)
    return _task_response("get", task)


async def task_update(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    status: TaskStatus | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Update one or more fields of an existing task.

    The primary use case is advancing a task through its lifecycle:
      pending → in_progress → completed

    Only the fields you explicitly pass will be changed; omitted fields keep
    their current values. At most one task may have status "in_progress" at a
    time — attempting to start a second task while another is in progress raises
    an error, forcing you to complete or revert the current one first.

    Args:
        task_id: The ID of the task to update (e.g., 'task_0001').
        title: Replace the task title. Pass null to leave unchanged.
        description: Replace the description. Pass "" to clear it, null to leave unchanged.
        status: New lifecycle status — "pending", "in_progress", or "completed".
        tags: Replace the tags list. Pass [] to clear all tags, null to leave unchanged.

    Returns:
        Structured result containing the full updated task object.

    Raises:
        ToolError: If the task is not found, the status value is invalid, or another
            task is already in_progress when trying to set status to "in_progress".
    """
    # Build update dict with only provided values
    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if tags is not None:
        kwargs["tags"] = tags

    if not kwargs:
        raise ToolError(
            "No fields provided to update. Set at least one of: title, description, status, tags."
        )

    task = await _TASK_MANAGER.update(task_id, **kwargs)
    return _task_response("update", task)


async def task_list(
    status: TaskStatus | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """List all tasks, optionally filtered by status or tag.

    Use this to get an overview of current work — what is pending, what is
    actively in progress, and what has been completed. Results are returned in
    creation order (task_0001 first), so the natural sequence of work is preserved.

    Call with no arguments to see every task. Use filters to focus on a subset:
    for example, status="pending" to find the next task to start, or a tag to
    see all tasks belonging to a particular area.

    Args:
        status: Narrow results to tasks with this status: "pending", "in_progress",
            or "completed". Pass null (default) to include all statuses.
        tag: Narrow results to tasks that carry this tag (case-insensitive).
            Pass null (default) to include all tags.

    Returns:
        Structured result with the matching task list, total count, and active filters.
    """
    tasks = await _TASK_MANAGER.list(status=status, tag=tag)
    return {
        "ok": True,
        "action": "list",
        "tasks": [task.to_dict() for task in tasks],
        "total": len(tasks),
        "filters": {
            "status": status,
            "tag": tag,
        },
    }


async def task_delete(task_id: str) -> dict[str, Any]:
    """Permanently remove a task.

    Use this to clean up tasks that are no longer relevant — cancelled work,
    duplicate entries, or tasks created by mistake. Deletion is irreversible.
    To free up space for new tasks when the 20-task limit is reached, delete
    completed tasks rather than leaving them to accumulate.

    Args:
        task_id: The ID of the task to delete (e.g., 'task_0001').

    Returns:
        Structured result confirming the deleted task ID.

    Raises:
        ToolError: If no task with the given ID exists.
    """
    await _TASK_MANAGER.delete(task_id)
    return {
        "ok": True,
        "action": "delete",
        "task_id": task_id,
    }
