"""Tests for task management tools."""

import pytest

from aiyo.tools.exceptions import ToolError
from aiyo.tools.tasks import (
    _TASK_MANAGER,
    task_create,
    task_delete,
    task_get,
    task_list,
    task_update,
)


@pytest.fixture(autouse=True)
def clear_tasks():
    """Clear all tasks before each test."""
    _TASK_MANAGER.clear()
    yield
    _TASK_MANAGER.clear()


class TestTaskCreate:
    """Tests for task_create function."""

    @pytest.mark.asyncio
    async def test_create_basic_task(self):
        """Test creating a basic task."""
        result = await task_create(tasks=[{"title": "Test Task"}])

        assert result["ok"] is True
        assert result["action"] == "create"
        assert result["task"]["title"] == "Test Task"
        assert result["task"]["id"].startswith("task_")
        assert result["total"] == 1
        assert len(result["tasks"]) == 1

    @pytest.mark.asyncio
    async def test_create_task_with_description(self):
        """Test creating a task with description."""
        result = await task_create(
            tasks=[{"title": "Test Task", "description": "This is a test description"}]
        )

        assert result["task"]["title"] == "Test Task"
        assert result["task"]["description"] == "This is a test description"

    @pytest.mark.asyncio
    async def test_create_task_with_priority(self):
        """Test creating a task with different priorities (5 levels)."""
        for priority in ("critical", "urgent", "high", "medium", "low"):
            result = await task_create(tasks=[{"title": f"Task {priority}", "priority": priority}])
            assert result["task"]["priority"] == priority

    @pytest.mark.asyncio
    async def test_create_task_with_tags(self):
        """Test creating a task with tags."""
        result = await task_create(
            tasks=[{"title": "Tagged Task", "tags": ["urgent", "bug", "frontend"]}]
        )

        assert result["task"]["tags"] == ["urgent", "bug", "frontend"]

    @pytest.mark.asyncio
    async def test_create_multiple_tasks(self):
        """Test batch task creation."""
        result = await task_create(
            tasks=[
                {"title": "Task A", "priority": "high", "tags": ["backend"]},
                {"title": "Task B", "description": "Second", "priority": "low"},
            ]
        )

        assert result["ok"] is True
        assert result["action"] == "create"
        assert result["total"] == 2
        assert [task["title"] for task in result["tasks"]] == ["Task A", "Task B"]
        assert result["tasks"][0]["priority"] == "high"
        assert result["tasks"][1]["description"] == "Second"

    @pytest.mark.asyncio
    async def test_create_multiple_tasks_requires_nonempty_list(self):
        """Test batch create rejects empty list."""
        with pytest.raises(ToolError, match="at least one item"):
            await task_create(tasks=[])

    @pytest.mark.asyncio
    async def test_create_task_empty_title_raises_error(self):
        """Test that empty title raises error."""
        with pytest.raises(ToolError, match="title is required"):
            await task_create(tasks=[{"title": ""}])

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority_raises_error(self):
        """Test that invalid priority raises error."""
        with pytest.raises(ToolError, match="Invalid priority"):
            await task_create(tasks=[{"title": "Test", "priority": "invalid"}])

    @pytest.mark.asyncio
    async def test_create_task_max_limit_raises_error(self):
        """Test that creating more than 20 tasks raises error."""
        # Create 20 tasks
        for i in range(20):
            await task_create(tasks=[{"title": f"Task {i}"}])

        # 21st task should fail
        with pytest.raises(ToolError, match="Task limit reached"):
            await task_create(tasks=[{"title": "Task 21"}])


class TestTaskGet:
    """Tests for task_get function."""

    @pytest.mark.asyncio
    async def test_get_existing_task(self):
        """Test getting an existing task."""
        await task_create(tasks=[{"title": "Task to Get"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_get(task_id=task_id)

        assert result["ok"] is True
        assert result["action"] == "get"
        assert result["task"]["title"] == "Task to Get"
        assert result["task"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_task_raises_error(self):
        """Test that getting nonexistent task raises error."""
        with pytest.raises(ToolError, match="not found"):
            await task_get(task_id="task_9999")


class TestTaskUpdate:
    """Tests for task_update function."""

    @pytest.mark.asyncio
    async def test_update_task_title(self):
        """Test updating task title."""
        await task_create(tasks=[{"title": "Original Title"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, title="Updated Title")

        assert result["ok"] is True
        assert result["action"] == "update"
        assert result["task"]["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_task_status(self):
        """Test updating task status."""
        await task_create(tasks=[{"title": "Task to Update"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, status="in_progress")
        assert result["task"]["status"] == "in_progress"

        result = await task_update(task_id=task_id, status="completed")
        assert result["task"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_only_one_task_can_be_in_progress(self):
        """Test that only one task can be in_progress at a time."""
        await task_create(tasks=[{"title": "First Task"}])
        await task_create(tasks=[{"title": "Second Task"}])

        task_ids = list(_TASK_MANAGER._tasks.keys())

        # Start first task
        await task_update(task_id=task_ids[0], status="in_progress")

        # Try to start second task should fail
        with pytest.raises(ToolError, match="already in progress"):
            await task_update(task_id=task_ids[1], status="in_progress")

        # Complete first task
        await task_update(task_id=task_ids[0], status="completed")

        # Now can start second task
        result = await task_update(task_id=task_ids[1], status="in_progress")
        assert result["task"]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_task_priority(self):
        """Test updating task priority (5 levels)."""
        await task_create(tasks=[{"title": "Task", "priority": "low"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Test all 5 priority levels
        for priority in ("critical", "urgent", "high", "medium"):
            result = await task_update(task_id=task_id, priority=priority)
            assert result["task"]["priority"] == priority

    @pytest.mark.asyncio
    async def test_update_task_tags(self):
        """Test updating task tags."""
        await task_create(tasks=[{"title": "Task", "tags": ["old"]}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, tags=["new", "tags"])

        assert result["task"]["tags"] == ["new", "tags"]

    @pytest.mark.asyncio
    async def test_update_task_can_clear_description_and_tags(self):
        """Test clearing fields via explicit empty values."""
        await task_create(tasks=[{"title": "Task", "description": "Has text", "tags": ["old"]}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, description="", tags=[])

        assert result["task"]["description"] == ""
        assert result["task"]["tags"] == []

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_raises_error(self):
        """Test that updating nonexistent task raises error."""
        with pytest.raises(ToolError, match="not found"):
            await task_update(task_id="task_9999", title="New Title")

    @pytest.mark.asyncio
    async def test_update_no_fields_raises_error(self):
        """Test that updating without any fields raises error."""
        await task_create(tasks=[{"title": "Task"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Call with only task_id, no other fields
        with pytest.raises(ToolError, match="No fields"):
            await task_update(task_id=task_id)

    @pytest.mark.asyncio
    async def test_update_invalid_status_raises_error(self):
        """Test that invalid status raises error."""
        await task_create(tasks=[{"title": "Task"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        with pytest.raises(ToolError, match="Invalid status"):
            await task_update(task_id=task_id, status="invalid_status")


class TestTaskList:
    """Tests for task_list function."""

    @pytest.mark.asyncio
    async def test_list_empty_tasks(self):
        """Test listing when no tasks exist."""
        result = await task_list()

        assert result["ok"] is True
        assert result["action"] == "list"
        assert result["tasks"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_all_tasks(self):
        """Test listing all tasks."""
        await task_create(tasks=[{"title": "Task 1"}])
        await task_create(tasks=[{"title": "Task 2"}])
        await task_create(tasks=[{"title": "Task 3"}])

        result = await task_list()

        titles = [task["title"] for task in result["tasks"]]
        assert result["total"] == 3
        assert titles == ["Task 1", "Task 2", "Task 3"]

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self):
        """Test filtering tasks by status."""
        await task_create(tasks=[{"title": "Pending Task"}])
        await task_create(tasks=[{"title": "In Progress Task"}])

        # Get the second task ID and update it
        task_ids = list(_TASK_MANAGER._tasks.keys())
        await task_update(task_id=task_ids[1], status="in_progress")

        result = await task_list(status="in_progress")

        assert result["total"] == 1
        assert result["tasks"][0]["title"] == "In Progress Task"

    @pytest.mark.asyncio
    async def test_list_filter_by_priority(self):
        """Test filtering tasks by priority (5 levels)."""
        await task_create(tasks=[{"title": "Low Priority", "priority": "low"}])
        await task_create(tasks=[{"title": "Critical Priority", "priority": "critical"}])

        result = await task_list(priority="critical")

        assert result["total"] == 1
        assert result["tasks"][0]["title"] == "Critical Priority"

    @pytest.mark.asyncio
    async def test_list_filter_by_tag(self):
        """Test filtering tasks by tag."""
        await task_create(tasks=[{"title": "Bug Task", "tags": ["bug"]}])
        await task_create(tasks=[{"title": "Feature Task", "tags": ["feature"]}])

        result = await task_list(tag="bug")

        assert result["total"] == 1
        assert result["tasks"][0]["title"] == "Bug Task"

    @pytest.mark.asyncio
    async def test_list_returns_tasks_sorted_by_priority_then_id(self):
        """Test that tasks are sorted by priority first, then by task ID."""
        # Create tasks in mixed priority order
        await task_create(tasks=[{"title": "Low Task 1", "priority": "low"}])
        await task_create(tasks=[{"title": "Critical Task", "priority": "critical"}])
        await task_create(tasks=[{"title": "Medium Task", "priority": "medium"}])
        await task_create(tasks=[{"title": "Low Task 2", "priority": "low"}])
        await task_create(tasks=[{"title": "Urgent Task", "priority": "urgent"}])

        result = await task_list()

        titles = [task["title"] for task in result["tasks"]]

        # Priority order: critical < urgent < medium < low
        assert titles.index("Critical Task") < titles.index("Urgent Task") < titles.index("Medium Task")
        assert titles.index("Medium Task") < titles.index("Low Task 1")
        assert titles.index("Medium Task") < titles.index("Low Task 2")
        # Same priority (low) should be sorted by ID (creation order)
        assert titles.index("Low Task 1") < titles.index("Low Task 2")


class TestTaskDelete:
    """Tests for task_delete function."""

    @pytest.mark.asyncio
    async def test_delete_existing_task(self):
        """Test deleting an existing task."""
        await task_create(tasks=[{"title": "Task to Delete"}])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_delete(task_id=task_id)

        assert result == {"ok": True, "action": "delete", "task_id": task_id}
        assert task_id not in _TASK_MANAGER._tasks

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task_raises_error(self):
        """Test that deleting nonexistent task raises error."""
        with pytest.raises(ToolError, match="not found"):
            await task_delete(task_id="task_9999")


class TestTaskWorkflow:
    """Integration tests for complete task workflows."""

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self):
        """Test complete task lifecycle from creation to completion."""
        # Create task with critical priority
        result = await task_create(
            tasks=[{
                "title": "Implement feature",
                "description": "Add new task management system",
                "priority": "critical",
                "tags": ["feature", "backend"],
            }]
        )
        assert result["action"] == "create"

        # Get task ID
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Get the task
        result = await task_get(task_id=task_id)
        assert result["task"]["title"] == "Implement feature"
        assert result["task"]["status"] == "pending"
        assert result["task"]["priority"] == "critical"

        # Update to in_progress
        result = await task_update(task_id=task_id, status="in_progress")
        assert result["task"]["status"] == "in_progress"

        # List active tasks
        result = await task_list(status="in_progress")
        assert result["tasks"][0]["title"] == "Implement feature"

        # Complete the task
        result = await task_update(task_id=task_id, status="completed")
        assert result["task"]["status"] == "completed"

        # Verify in completed list
        result = await task_list(status="completed")
        assert result["tasks"][0]["title"] == "Implement feature"

        # Delete the task (when done, just delete it)
        result = await task_delete(task_id=task_id)
        assert result["task_id"] == task_id

        # Verify no tasks
        result = await task_list()
        assert result["tasks"] == []
