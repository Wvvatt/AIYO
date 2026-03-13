"""Shell execution tool."""

import subprocess

from aiyo.config import settings


def run_shell_command(command: str, timeout: int = 60) -> str:
    """Run a shell command and return its combined stdout and stderr output.

    Args:
        command: The shell command to execute.
        timeout: Maximum seconds to wait (1–300, default 60).
    """
    timeout = max(1, min(timeout, 300))
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=settings.work_dir,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        if error:
            output = f"{output}\n[stderr]\n{error}".strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s."
