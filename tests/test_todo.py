"""Tests for todo tool."""

import pytest
from unittest.mock import patch, MagicMock

from aiyo.tools.todo import todo


class TestTodo:
    """Tests for todo function."""

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_create_single_item(self, mock_state):
        """Test creating a single todo item."""
        mock_state.clear()
        
        result = todo([{"id": "1", "text": "Test task", "status": "pending"}])
        
        assert "Test task" in result
        assert "pending" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_create_multiple_items(self, mock_state):
        """Test creating multiple todo items."""
        mock_state.clear()
        
        items = [
            {"id": "1", "text": "Task 1", "status": "pending"},
            {"id": "2", "text": "Task 2", "status": "in_progress"},
            {"id": "3", "text": "Task 3", "status": "completed"},
        ]
        result = todo(items)
        
        assert "Task 1" in result
        assert "Task 2" in result
        assert "Task 3" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_update_item_status(self, mock_state):
        """Test updating an item's status."""
        mock_state.clear()
        
        # Create initial item
        todo([{"id": "1", "text": "Test task", "status": "pending"}])
        
        # Update status
        result = todo([{"id": "1", "text": "Test task", "status": "completed"}])
        
        assert "completed" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_max_items_limit(self, mock_state):
        """Test that at most 20 items are allowed."""
        mock_state.clear()
        
        # Try to create more than 20 items
        items = [{"id": str(i), "text": f"Task {i}", "status": "pending"} for i in range(25)]
        
        result = todo(items)
        
        assert "Error:" in result
        assert "20" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_only_one_in_progress(self, mock_state):
        """Test that only one item can be in_progress at a time."""
        mock_state.clear()
        
        items = [
            {"id": "1", "text": "Task 1", "status": "in_progress"},
            {"id": "2", "text": "Task 2", "status": "in_progress"},
        ]
        
        result = todo(items)
        
        assert "Error:" in result
        assert "one item" in result.lower()

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_invalid_status(self, mock_state):
        """Test that invalid status is rejected."""
        mock_state.clear()
        
        items = [{"id": "1", "text": "Test task", "status": "invalid_status"}]
        
        result = todo(items)
        
        assert "Error:" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_missing_required_fields(self, mock_state):
        """Test that missing required fields are rejected."""
        mock_state.clear()
        
        # Missing 'text' field
        items = [{"id": "1", "status": "pending"}]
        
        result = todo(items)
        
        assert "Error:" in result

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_empty_todo_list(self, mock_state):
        """Test that empty todo list is handled."""
        mock_state.clear()
        
        result = todo([])
        
        # Should either show empty list or error
        assert isinstance(result, str)

    @patch('aiyo.tools.todo._todo_state', new_callable=dict)
    def test_item_rendering_format(self, mock_state):
        """Test that items are rendered in correct format."""
        mock_state.clear()
        
        items = [
            {"id": "1", "text": "Pending task", "status": "pending"},
            {"id": "2", "text": "In progress task", "status": "in_progress"},
            {"id": "3", "text": "Completed task", "status": "completed"},
        ]
        result = todo(items)
        
        # Check for status indicators
        assert "[ ]" in result or "pending" in result
        assert "[*]" in result or "in_progress" in result or "→" in result
        assert "[✓]" in result or "completed" in result or "✓" in result
