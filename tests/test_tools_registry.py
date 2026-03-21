"""Tests for tool permission grouping."""

from aiyo.tools import READ_TOOLS, WRITE_TOOLS


def _names(tools):
    return {tool.__name__ for tool in tools}


def test_task_mutations_are_write_tools():
    read_names = _names(READ_TOOLS)
    write_names = _names(WRITE_TOOLS)

    assert "task_create" not in read_names
    assert "task_update" not in read_names
    assert "task_delete" not in read_names

    assert "task_create" in write_names
    assert "task_update" in write_names
    assert "task_delete" in write_names
