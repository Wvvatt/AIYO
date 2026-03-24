"""Tests for tool permission grouping."""

from aiyo.tools import READ_TOOLS, WRITE_TOOLS


def _names(tools):
    return {tool.__name__ for tool in tools}


def test_task_tools_are_read_tools():
    read_names = _names(READ_TOOLS)
    write_names = _names(WRITE_TOOLS)

    assert "task_create" in read_names
    assert "task_update" in read_names
    assert "task_delete" in read_names
    assert "task_get" in read_names
    assert "task_list" in read_names

    assert "task_create" not in write_names
    assert "task_update" not in write_names
    assert "task_delete" not in write_names
