"""Tests for filesystem tools."""

import os
import tempfile
from pathlib import Path

import pytest

from aiyo.tools.filesystem import (
    read_file,
    write_file,
    str_replace_file,
    list_directory,
    glob_files,
    grep_files,
)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Store original work_dir
        from aiyo.tools._sandbox import _WORK_DIR
        original_work_dir = _WORK_DIR
        
        # Set new work_dir
        from aiyo.tools._sandbox import set_work_dir
        set_work_dir(Path(tmpdir))
        
        yield Path(tmpdir)
        
        # Restore original work_dir
        set_work_dir(original_work_dir)


class TestReadFile:
    """Tests for read_file function."""

    def test_read_existing_file(self, temp_workspace):
        """Test reading an existing file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!\nLine 2\nLine 3")
        
        result = read_file("test.txt")
        
        assert "Hello, World!" in result
        assert "Line 2" in result
        assert "File: test.txt" in result

    def test_read_nonexistent_file(self, temp_workspace):
        """Test reading a file that doesn't exist."""
        result = read_file("nonexistent.txt")
        
        assert "Error:" in result
        assert "not found" in result

    def test_read_with_line_offset(self, temp_workspace):
        """Test reading with line offset."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4")
        
        result = read_file("test.txt", line_offset=2)
        
        assert "Line 2" in result
        assert "Line 1" not in result

    def test_read_directory_instead_of_file(self, temp_workspace):
        """Test reading a directory instead of a file."""
        (temp_workspace / "subdir").mkdir()
        
        result = read_file("subdir")
        
        assert "Error:" in result
        assert "is not a file" in result


class TestWriteFile:
    """Tests for write_file function."""

    def test_write_new_file(self, temp_workspace):
        """Test writing to a new file."""
        result = write_file("new_file.txt", "Hello, World!")
        
        assert "Written" in result
        assert (temp_workspace / "new_file.txt").exists()
        assert (temp_workspace / "new_file.txt").read_text() == "Hello, World!"

    def test_overwrite_existing_file(self, temp_workspace):
        """Test overwriting an existing file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Old content")
        
        result = write_file("test.txt", "New content", mode="overwrite")
        
        assert "Written" in result
        assert test_file.read_text() == "New content"

    def test_append_to_file(self, temp_workspace):
        """Test appending to a file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("First line\n")
        
        result = write_file("test.txt", "Second line", mode="append")
        
        assert "Written" in result
        content = test_file.read_text()
        assert "First line" in content
        assert "Second line" in content

    def test_write_invalid_mode(self, temp_workspace):
        """Test writing with invalid mode."""
        result = write_file("test.txt", "content", mode="invalid")
        
        assert "Error:" in result
        assert "mode must be" in result

    def test_write_to_nonexistent_directory(self, temp_workspace):
        """Test writing to a non-existent directory."""
        result = write_file("nonexistent_dir/file.txt", "content")
        
        assert "Error:" in result
        assert "does not exist" in result


class TestStrReplaceFile:
    """Tests for str_replace_file function."""

    def test_replace_single_occurrence(self, temp_workspace):
        """Test replacing a single occurrence."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World! Hello!")
        
        result = str_replace_file("test.txt", "World", "Universe")
        
        assert "Replaced 1 occurrence" in result
        assert test_file.read_text() == "Hello, Universe! Hello!"

    def test_replace_no_occurrence(self, temp_workspace):
        """Test replacing when string not found."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!")
        
        result = str_replace_file("test.txt", "NonExistent", "Replacement")
        
        assert "Error:" in result
        assert "not found" in result
        assert test_file.read_text() == "Hello, World!"

    def test_replace_multiple_occurrences(self, temp_workspace):
        """Test replacing when multiple occurrences exist."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello Hello Hello")
        
        result = str_replace_file("test.txt", "Hello", "Hi")
        
        assert "Error:" in result
        assert "found 3 times" in result
        assert test_file.read_text() == "Hello Hello Hello"

    def test_replace_in_nonexistent_file(self, temp_workspace):
        """Test replacing in a non-existent file."""
        result = str_replace_file("nonexistent.txt", "old", "new")
        
        assert "Error:" in result
        assert "not found" in result


class TestListDirectory:
    """Tests for list_directory function."""

    def test_list_empty_directory(self, temp_workspace):
        """Test listing an empty directory."""
        result = list_directory(".")
        
        assert result == "(empty directory)"

    def test_list_with_files_and_dirs(self, temp_workspace):
        """Test listing directory with files and subdirectories."""
        (temp_workspace / "file1.txt").write_text("content")
        (temp_workspace / "file2.txt").write_text("content")
        (temp_workspace / "subdir").mkdir()
        
        result = list_directory(".")
        
        assert "DIR subdir" in result
        assert "FILE file1.txt" in result
        assert "FILE file2.txt" in result

    def test_list_nonexistent_directory(self, temp_workspace):
        """Test listing a non-existent directory."""
        result = list_directory("nonexistent")
        
        assert "Error:" in result
        assert "not found" in result


class TestGlobFiles:
    """Tests for glob_files function."""

    def test_glob_pattern(self, temp_workspace):
        """Test glob pattern matching."""
        (temp_workspace / "test1.py").write_text("")
        (temp_workspace / "test2.py").write_text("")
        (temp_workspace / "test.txt").write_text("")
        
        result = glob_files("*.py")
        
        assert "test1.py" in result
        assert "test2.py" in result
        assert "test.txt" not in result

    def test_glob_no_matches(self, temp_workspace):
        """Test glob with no matches."""
        (temp_workspace / "test.txt").write_text("")
        
        result = glob_files("*.py")
        
        assert "No files matched" in result

    def test_glob_nonexistent_directory(self, temp_workspace):
        """Test glob in non-existent directory."""
        result = glob_files("*.py", directory="nonexistent")
        
        assert "Error:" in result
        assert "not found" in result


class TestGrepFiles:
    """Tests for grep_files function."""

    def test_grep_find_matches(self, temp_workspace):
        """Test finding matches with grep."""
        test_file = temp_workspace / "test.py"
        test_file.write_text("def hello():\n    pass\n\ndef world():\n    pass")
        
        result = grep_files("def ", path=".")
        
        assert "def hello()" in result
        assert "def world()" in result
        assert "test.py" in result

    def test_grep_no_matches(self, temp_workspace):
        """Test grep with no matches."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!")
        
        result = grep_files("nonexistent", path=".")
        
        assert "No matches" in result

    def test_grep_invalid_regex(self, temp_workspace):
        """Test grep with invalid regex."""
        result = grep_files("[invalid", path=".")
        
        assert "Error:" in result
        assert "invalid regex" in result

    def test_grep_ignore_case(self, temp_workspace):
        """Test grep with case-insensitive search."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello\nHELLO\nhello")
        
        result = grep_files("hello", path=".", ignore_case=True)
        
        assert result.count("Hello") + result.count("HELLO") + result.count("hello") >= 3

    def test_grep_with_context_lines(self, temp_workspace):
        """Test grep with context lines."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Line 1\nLine 2\nTarget Line\nLine 4\nLine 5")
        
        result = grep_files("Target", path=".", context_lines=1)
        
        assert "Line 2" in result
        assert "Target Line" in result
        assert "Line 4" in result
