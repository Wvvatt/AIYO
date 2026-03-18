"""Tests for task management tools."""

import pytest

from aiyo.tools.exceptions import ToolError
from aiyo.tools.tasks import (
    task_create,
    task_delete,
    task_get,
    task_list,
    task_update,
    _TASK_MANAGER,
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
        result = await task_create(title="Test Task")

        assert "Task created successfully" in result
        assert "Test Task" in result
        assert "task_" in result

    @pytest.mark.asyncio
    async def test_create_task_with_description(self):
        """Test creating a task with description."""
        result = await task_create(
            title="Test Task",
            description="This is a test description"
        )

        assert "Test Task" in result
        assert "This is a test description" in result

    @pytest.mark.asyncio
    async def test_create_task_with_priority(self):
        """Test creating a task with different priorities (5 levels)."""
        priority_icons = {"critical": "!!!!", "urgent": "!!!", "high": "!!", "medium": "!", "low": ""}
        for priority, icon in priority_icons.items():
            result = await task_create(title=f"Task {priority}", priority=priority)
            if icon:
                assert icon in result

    @pytest.mark.asyncio
    async def test_create_task_with_tags(self):
        """Test creating a task with tags."""
        result = await task_create(
            title="Tagged Task",
            tags=["urgent", "bug", "frontend"]
        )

        assert "urgent" in result
        assert "bug" in result

    @pytest.mark.asyncio
    async def test_create_task_empty_title_raises_error(self):
        """Test that empty title raises error."""
        with pytest.raises(ToolError, match="title is required"):
            await task_create(title="")

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority_raises_error(self):
        """Test that invalid priority raises error."""
        with pytest.raises(ToolError, match="Invalid priority"):
            await task_create(title="Test", priority="invalid")

    @pytest.mark.asyncio
    async def test_create_task_max_limit_raises_error(self):
        """Test that creating more than 20 tasks raises error."""
        # Create 20 tasks
        for i in range(20):
            await task_create(title=f"Task {i}")

        # 21st task should fail
        with pytest.raises(ToolError, match="Task limit reached"):
            await task_create(title="Task 21")


class TestTaskGet:
    """Tests for task_get function."""

    @pytest.mark.asyncio
    async def test_get_existing_task(self):
        """Test getting an existing task."""
        await task_create(title="Task to Get")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_get(task_id=task_id)

        assert "Task to Get" in result
        assert task_id in result

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
        await task_create(title="Original Title")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, title="Updated Title")

        assert "Updated Title" in result
        assert "updated successfully" in result

    @pytest.mark.asyncio
    async def test_update_task_status(self):
        """Test updating task status."""
        await task_create(title="Task to Update")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, status="in_progress")
        assert "[>]" in result

        result = await task_update(task_id=task_id, status="completed")
        assert "[x]" in result

    @pytest.mark.asyncio
    async def test_only_one_task_can_be_in_progress(self):
        """Test that only one task can be in_progress at a time."""
        await task_create(title="First Task")
        await task_create(title="Second Task")

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
        assert "[>]" in result

    @pytest.mark.asyncio
    async def test_update_task_priority(self):
        """Test updating task priority (5 levels)."""
        await task_create(title="Task", priority="low")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Test all 5 priority levels
        priority_icons = {"critical": "!!!!", "urgent": "!!!", "high": "!!", "medium": "!"}
        for priority, icon in priority_icons.items():
            result = await task_update(task_id=task_id, priority=priority)
            assert icon in result

    @pytest.mark.asyncio
    async def test_update_task_tags(self):
        """Test updating task tags."""
        await task_create(title="Task", tags=["old"])
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_update(task_id=task_id, tags=["new", "tags"])

        assert "new" in result
        assert "tags" in result

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_raises_error(self):
        """Test that updating nonexistent task raises error."""
        with pytest.raises(ToolError, match="not found"):
            await task_update(task_id="task_9999", title="New Title")

    @pytest.mark.asyncio
    async def test_update_no_fields_raises_error(self):
        """Test that updating without any fields raises error."""
        await task_create(title="Task")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Call with only task_id, no other fields
        with pytest.raises(ToolError, match="No fields"):
            await task_update(task_id=task_id)

    @pytest.mark.asyncio
    async def test_update_invalid_status_raises_error(self):
        """Test that invalid status raises error."""
        await task_create(title="Task")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        with pytest.raises(ToolError, match="Invalid status"):
            await task_update(task_id=task_id, status="invalid_status")


class TestTaskList:
    """Tests for task_list function."""

    @pytest.mark.asyncio
    async def test_list_empty_tasks(self):
        """Test listing when no tasks exist."""
        result = await task_list()

        assert "No tasks found" in result

    @pytest.mark.asyncio
    async def test_list_all_tasks(self):
        """Test listing all tasks."""
        await task_create(title="Task 1")
        await task_create(title="Task 2")
        await task_create(title="Task 3")

        result = await task_list()

        assert "Total: 3 task(s)" in result
        assert "Task 1" in result
        assert "Task 2" in result
        assert "Task 3" in result

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self):
        """Test filtering tasks by status."""
        await task_create(title="Pending Task")
        await task_create(title="In Progress Task")

        # Get the second task ID and update it
        task_ids = list(_TASK_MANAGER._tasks.keys())
        await task_update(task_id=task_ids[1], status="in_progress")

        result = await task_list(status="in_progress")

        assert "In Progress Task" in result
        assert "Pending Task" not in result

    @pytest.mark.asyncio
    async def test_list_filter_by_priority(self):
        """Test filtering tasks by priority (5 levels)."""
        await task_create(title="Low Priority", priority="low")
        await task_create(title="Critical Priority", priority="critical")

        result = await task_list(priority="critical")

        assert "Critical Priority" in result
        assert "Low Priority" not in result

    @pytest.mark.asyncio
    async def test_list_filter_by_tag(self):
        """Test filtering tasks by tag."""
        await task_create(title="Bug Task", tags=["bug"])
        await task_create(title="Feature Task", tags=["feature"])

        result = await task_list(tag="bug")

        assert "Bug Task" in result
        assert "Feature Task" not in result

    @pytest.mark.asyncio
    async def test_list_returns_tasks_sorted_by_priority_then_id(self):
        """Test that tasks are sorted by priority first, then by task ID."""
        # Create tasks in mixed priority order
        await task_create(title="Low Task 1", priority="low")
        await task_create(title="Critical Task", priority="critical")
        await task_create(title="Medium Task", priority="medium")
        await task_create(title="Low Task 2", priority="low")
        await task_create(title="Urgent Task", priority="urgent")

        result = await task_list()

        lines = result.split("\n")
        # Find positions
        critical_idx = next(i for i, line in enumerate(lines) if "Critical Task" in line)
        urgent_idx = next(i for i, line in enumerate(lines) if "Urgent Task" in line)
        medium_idx = next(i for i, line in enumerate(lines) if "Medium Task" in line)
        low1_idx = next(i for i, line in enumerate(lines) if "Low Task 1" in line)
        low2_idx = next(i for i, line in enumerate(lines) if "Low Task 2" in line)

        # Priority order: critical < urgent < medium < low
        assert critical_idx < urgent_idx < medium_idx < low1_idx
        assert critical_idx < urgent_idx < medium_idx < low2_idx
        # Same priority (low) should be sorted by ID (creation order)
        assert low1_idx < low2_idx


class TestTaskDelete:
    """Tests for task_delete function."""

    @pytest.mark.asyncio
    async def test_delete_existing_task(self):
        """Test deleting an existing task."""
        await task_create(title="Task to Delete")
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        result = await task_delete(task_id=task_id)

        assert "deleted successfully" in result
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
            title="Implement feature",
            description="Add new task management system",
            priority="critical",
            tags=["feature", "backend"]
        )
        assert "created successfully" in result

        # Get task ID
        task_id = list(_TASK_MANAGER._tasks.keys())[0]

        # Get the task
        result = await task_get(task_id=task_id)
        assert "Implement feature" in result
        assert "[ ]" in result
        assert "!!!!" in result

        # Update to in_progress
        result = await task_update(task_id=task_id, status="in_progress")
        assert "[>]" in result

        # List active tasks
        result = await task_list(status="in_progress")
        assert "Implement feature" in result

        # Complete the task
        result = await task_update(task_id=task_id, status="completed")
        assert "[x]" in result

        # Verify in completed list
        result = await task_list(status="completed")
        assert "Implement feature" in result

        # Delete the task (when done, just delete it)
        result = await task_delete(task_id=task_id)
        assert "deleted successfully" in result

        # Verify no tasks
        result = await task_list()
        assert "No tasks found" in result
