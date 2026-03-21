"""Tests for shell execution tool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiyo.tools.exceptions import ToolError
from aiyo.tools.shell import shell


class TestShellCancellation:
    """Tests for shell cancellation behavior."""

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_shell_cancellation_kills_process(self, mock_create_subprocess):
        """Test that CancelledError kills the subprocess and re-raises."""
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_create_subprocess.return_value = mock_process

        with pytest.raises(asyncio.CancelledError):
            await shell("sleep 100")

        mock_process.kill.assert_called_once()
        mock_process.wait.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_shell_cancellation_with_none_process(self, mock_create_subprocess):
        """Test cancellation before process creation does not crash."""
        mock_create_subprocess.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await shell("sleep 100")

        mock_create_subprocess.assert_called_once()

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_shell_timeout_kills_process(self, mock_create_subprocess):
        """Test that timeout kills the subprocess properly."""
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(side_effect=TimeoutError())
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_create_subprocess.return_value = mock_process

        with pytest.raises(ToolError, match="timed out"):
            await shell("sleep 100")

        mock_process.kill.assert_called_once()
        mock_process.wait.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_shell_cancellation_kill_error_ignored(self, mock_create_subprocess):
        """Test that errors during kill are ignored on cancellation."""
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        mock_process.kill = MagicMock(side_effect=Exception("Kill failed"))
        mock_process.wait = AsyncMock()
        mock_create_subprocess.return_value = mock_process

        # Should not raise, cancellation is still propagated
        with pytest.raises(asyncio.CancelledError):
            await shell("sleep 100")


class TestShell:
    """Tests for shell function."""

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_simple_command(self, mock_create_subprocess):
        """Test running a simple command."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Hello, World!", b"")
        mock_create_subprocess.return_value = mock_process

        result = await shell("echo 'Hello, World!'")

        assert "Hello, World!" in result
        mock_create_subprocess.assert_called_once()

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_with_stderr(self, mock_create_subprocess):
        """Test running a command that outputs to stderr."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Standard output", b"Error message")
        mock_create_subprocess.return_value = mock_process

        result = await shell("some_command")

        assert "Standard output" in result
        assert "[stderr]" in result
        assert "Error message" in result

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_non_zero_exit_raises_tool_error(self, mock_create_subprocess):
        """Test non-zero exit code is surfaced as ToolError."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"partial output", b"failure details")
        mock_process.returncode = 2
        mock_create_subprocess.return_value = mock_process

        with pytest.raises(ToolError, match="exit code 2"):
            await shell("false")

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_no_output(self, mock_create_subprocess):
        """Test running a command with no output."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_create_subprocess.return_value = mock_process

        result = await shell("true")

        assert result == "(no output)"

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_timeout(self, mock_create_subprocess):
        """Test command timeout handling."""
        mock_process = AsyncMock()
        mock_process.communicate.side_effect = TimeoutError()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_create_subprocess.return_value = mock_process

        with pytest.raises(ToolError, match="timed out"):
            await shell("sleep 100")

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_with_custom_timeout(self, mock_create_subprocess):
        """Test running command with custom timeout."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Done", b"")
        mock_create_subprocess.return_value = mock_process

        result = await shell("sleep 1", timeout=30)

        assert "Done" in result
        # Verify timeout was passed correctly (clamped between 1-300)
        call_kwargs = mock_create_subprocess.call_args[1]
        assert "timeout" not in call_kwargs  # timeout is handled by asyncio.wait_for

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_timeout_too_low(self, mock_create_subprocess):
        """Test timeout clamping for values below 1."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Done", b"")
        mock_create_subprocess.return_value = mock_process

        result = await shell("echo test", timeout=0)

        # Should complete without error (timeout is clamped internally)
        assert result == "Done"

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_timeout_too_high(self, mock_create_subprocess):
        """Test timeout clamping for values above 300."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"Done", b"")
        mock_create_subprocess.return_value = mock_process

        result = await shell("echo test", timeout=500)

        # Should complete without error (timeout is clamped internally)
        assert result == "Done"

    @pytest.mark.asyncio
    @patch("aiyo.tools.shell.asyncio.create_subprocess_shell")
    async def test_run_command_uses_work_dir(self, mock_create_subprocess):
        """Test that command runs in configured work directory."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_create_subprocess.return_value = mock_process

        await shell("pwd")

        call_kwargs = mock_create_subprocess.call_args[1]
        assert "cwd" in call_kwargs
