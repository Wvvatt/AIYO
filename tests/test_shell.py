"""Tests for shell execution tool."""

from unittest.mock import MagicMock, patch

from aiyo.tools.shell import run_shell_command


class TestRunShellCommand:
    """Tests for run_shell_command function."""

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_simple_command(self, mock_run):
        """Test running a simple command."""
        mock_result = MagicMock()
        mock_result.stdout = "Hello, World!"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_shell_command("echo 'Hello, World!'")

        assert "Hello, World!" in result
        mock_run.assert_called_once()

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_with_stderr(self, mock_run):
        """Test running a command that outputs to stderr."""
        mock_result = MagicMock()
        mock_result.stdout = "Standard output"
        mock_result.stderr = "Error message"
        mock_run.return_value = mock_result

        result = run_shell_command("some_command")

        assert "Standard output" in result
        assert "[stderr]" in result
        assert "Error message" in result

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_no_output(self, mock_run):
        """Test running a command with no output."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_shell_command("true")

        assert result == "(no output)"

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_timeout(self, mock_run):
        """Test command timeout handling."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=60)

        result = run_shell_command("sleep 100")

        assert "Error:" in result
        assert "timed out" in result

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_with_custom_timeout(self, mock_run):
        """Test running command with custom timeout."""
        mock_result = MagicMock()
        mock_result.stdout = "Done"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_shell_command("sleep 1", timeout=30)

        assert "Done" in result
        # Verify timeout was passed correctly (clamped between 1-300)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 30

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_timeout_too_low(self, mock_run):
        """Test timeout clamping for values below 1."""
        mock_result = MagicMock()
        mock_result.stdout = "Done"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_shell_command("echo test", timeout=0)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 1  # Should be clamped to 1

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_timeout_too_high(self, mock_run):
        """Test timeout clamping for values above 300."""
        mock_result = MagicMock()
        mock_result.stdout = "Done"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_shell_command("echo test", timeout=500)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 300  # Should be clamped to 300

    @patch("aiyo.tools.shell.subprocess.run")
    def test_run_command_uses_work_dir(self, mock_run):
        """Test that command runs in configured work directory."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        run_shell_command("pwd")

        call_kwargs = mock_run.call_args[1]
        assert "cwd" in call_kwargs
