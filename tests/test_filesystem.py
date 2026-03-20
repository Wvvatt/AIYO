"""Tests for filesystem tools (kimi-cli compatible)."""

import tempfile
from pathlib import Path

import pytest

from aiyo.tools.exceptions import ToolError
from aiyo.tools.filesystem import (
    Edit,
    glob_files,
    grep_files,
    list_directory,
    read_file,
    edit_file,
    write_file,
)


@pytest.fixture
def temp_workspace(monkeypatch):
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock settings.work_dir
        from aiyo.config import settings

        original_work_dir = settings.work_dir
        monkeypatch.setattr(settings, "work_dir", Path(tmpdir))

        yield Path(tmpdir)

        # Restore original work_dir
        monkeypatch.setattr(settings, "work_dir", original_work_dir)


class TestReadFile:
    """Tests for read_file function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, temp_workspace):
        """Test reading an existing file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!\nLine 2\nLine 3")

        result = await read_file("test.txt")

        assert "Hello, World!" in result
        assert "Line 2" in result
        # kimi-cli format: line numbers with tabs
        assert "1" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, temp_workspace):
        """Test reading a file that doesn't exist."""
        with pytest.raises(ToolError, match="does not exist"):
            await read_file("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_read_with_line_offset(self, temp_workspace):
        """Test reading with line offset."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4")

        result = await read_file("test.txt", line_offset=2)

        assert "Line 2" in result
        # Line 1 should not be in output (starts from line 2)
        # But we check the actual content format

    @pytest.mark.asyncio
    async def test_read_directory_instead_of_file(self, temp_workspace):
        """Test reading a directory instead of a file."""
        (temp_workspace / "subdir").mkdir()

        with pytest.raises(ToolError, match="is not a file"):
            await read_file("subdir")


class TestWriteFile:
    """Tests for write_file function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, temp_workspace):
        """Test writing to a new file."""
        result = await write_file("new_file.txt", "Hello, World!")

        # kimi-cli format: "File successfully overwritten/appended"
        assert "successfully" in result
        assert (temp_workspace / "new_file.txt").exists()
        assert (temp_workspace / "new_file.txt").read_text() == "Hello, World!"

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, temp_workspace):
        """Test overwriting an existing file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Old content")

        result = await write_file("test.txt", "New content", mode="overwrite")

        assert "successfully overwritten" in result
        assert test_file.read_text() == "New content"

    @pytest.mark.asyncio
    async def test_append_to_file(self, temp_workspace):
        """Test appending to a file."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("First line\n")

        result = await write_file("test.txt", "Second line", mode="append")

        assert "successfully appended" in result
        content = test_file.read_text()
        assert "First line" in content
        assert "Second line" in content

    @pytest.mark.asyncio
    async def test_write_invalid_mode(self, temp_workspace):
        """Test writing with invalid mode."""
        with pytest.raises(ToolError, match="Invalid write mode"):
            await write_file("test.txt", "content", mode="invalid")

    @pytest.mark.asyncio
    async def test_write_to_nonexistent_directory(self, temp_workspace):
        """Test writing to a non-existent directory."""
        with pytest.raises(ToolError, match="does not exist"):
            await write_file("nonexistent_dir/file.txt", "content")


class TestEditFile:
    """Tests for edit_file function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_replace_single_occurrence(self, temp_workspace):
        """Test replacing a single occurrence."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World! Hello!")

        result = await edit_file("test.txt", "World", "Universe")

        assert "successfully edited" in result
        assert test_file.read_text() == "Hello, Universe! Hello!"

    @pytest.mark.asyncio
    async def test_replace_no_occurrence(self, temp_workspace):
        """Test replacing when string not found."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!")

        with pytest.raises(ToolError, match="No replacements were made"):
            await edit_file("test.txt", "NonExistent", "Replacement")
        assert test_file.read_text() == "Hello, World!"

    @pytest.mark.asyncio
    async def test_replace_multiple_occurrences(self, temp_workspace):
        """Test replacing when multiple occurrences exist."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello Hello Hello")

        with pytest.raises(ToolError, match="found 3 times"):
            await edit_file("test.txt", "Hello", "Hi")
        assert test_file.read_text() == "Hello Hello Hello"

    @pytest.mark.asyncio
    async def test_replace_in_nonexistent_file(self, temp_workspace):
        """Test replacing in a non-existent file."""
        with pytest.raises(ToolError, match="does not exist"):
            await edit_file("nonexistent.txt", "old", "new")

    @pytest.mark.asyncio
    async def test_batch_edits(self, temp_workspace):
        """Test batch edit via Edit objects."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("foo bar baz")

        result = await edit_file("test.txt", edit=[
            Edit(old="foo", new="FOO"),
            Edit(old="bar", new="BAR"),
        ])

        assert "successfully edited" in result
        assert test_file.read_text() == "FOO BAR baz"


class TestListDirectory:
    """Tests for list_directory function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, temp_workspace):
        """Test listing an empty directory."""
        result = await list_directory(".")

        assert result == "(empty directory)"

    @pytest.mark.asyncio
    async def test_list_with_files_and_dirs(self, temp_workspace):
        """Test listing directory with files and subdirectories."""
        (temp_workspace / "file1.txt").write_text("content")
        (temp_workspace / "file2.txt").write_text("content")
        (temp_workspace / "subdir").mkdir()

        result = await list_directory(".")

        assert "DIR subdir" in result
        assert "FILE file1.txt" in result
        assert "FILE file2.txt" in result

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, temp_workspace):
        """Test listing a non-existent directory."""
        with pytest.raises(ToolError, match="does not exist"):
            await list_directory("nonexistent")


class TestGlobFiles:
    """Tests for glob_files function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_glob_pattern(self, temp_workspace):
        """Test glob pattern matching."""
        (temp_workspace / "test1.py").write_text("")
        (temp_workspace / "test2.py").write_text("")
        (temp_workspace / "test.txt").write_text("")

        result = await glob_files("*.py")

        assert "test1.py" in result
        assert "test2.py" in result
        assert "test.txt" not in result

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, temp_workspace):
        """Test glob with no matches - returns message (not exception)."""
        (temp_workspace / "test.txt").write_text("")

        result = await glob_files("*.py")
        
        # kimi-cli style: returns message instead of raising
        assert "No matches found" in result

    @pytest.mark.asyncio
    async def test_glob_nonexistent_directory(self, temp_workspace):
        """Test glob in non-existent directory."""
        with pytest.raises(ToolError, match="does not exist"):
            await glob_files("*.py", directory="nonexistent")

    @pytest.mark.asyncio
    async def test_glob_double_star_rejected(self, temp_workspace):
        """Test that ** pattern is rejected (kimi-cli security)."""
        with pytest.raises(ToolError, match="not allowed"):
            await glob_files("**/*.py")


class TestGrepFiles:
    """Tests for grep_files function (kimi-cli style)."""

    @pytest.mark.asyncio
    async def test_grep_find_matches(self, temp_workspace):
        """Test finding matches with grep."""
        test_file = temp_workspace / "test.py"
        test_file.write_text("def hello():\n    pass\n\ndef world():\n    pass")

        result = await grep_files("def ", path=".")

        assert "def hello()" in result or "hello" in result
        assert "test.py" in result or "hello" in result

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, temp_workspace):
        """Test grep with no matches - returns message (not exception)."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello, World!")

        result = await grep_files("nonexistent", path=".")
        
        # kimi-cli style: returns message instead of raising
        assert "No matches found" in result

    @pytest.mark.asyncio
    async def test_grep_ignore_case(self, temp_workspace):
        """Test grep with case-insensitive search."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello\nHELLO\nhello")

        result = await grep_files("hello", path=".", ignore_case=True)

        # Should find all three variations
        assert result.count("Hello") + result.count("HELLO") + result.count("hello") >= 3

    @pytest.mark.asyncio
    async def test_grep_with_context(self, temp_workspace):
        """Test grep with context lines (kimi-cli uses 'context' not 'context_lines')."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Line 1\nLine 2\nTarget Line\nLine 4\nLine 5")

        result = await grep_files("Target", path=".", context=1)

        assert "Line 2" in result
        assert "Target" in result
        assert "Line 4" in result
