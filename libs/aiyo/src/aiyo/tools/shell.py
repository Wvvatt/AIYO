"""Shell execution tool."""

import asyncio

from aiyo.config import settings

from .exceptions import ToolError


async def shell(command: str, timeout: int = 60) -> str:
    """Run a shell command and return its combined stdout and stderr output.

    Args:
        command: The shell command to execute.
        timeout: Maximum seconds to wait (1–300, default 60).

    Raises:
        ToolError: If command times out or fails to execute.
        asyncio.CancelledError: If the operation was cancelled (e.g., user pressed Ctrl-C).
    """
    timeout = max(1, min(timeout, 300))
    process = None
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.work_dir,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        output = stdout.decode().strip()
        error = stderr.decode().strip()
        returncode = process.returncode if isinstance(process.returncode, int) else 0
        if returncode != 0:
            details = output
            if error:
                details = f"{details}\n[stderr]\n{error}".strip()
            if not details:
                details = "(no output)"
            raise ToolError(f"command failed with exit code {returncode}.\n{details}")
        if error:
            output = f"{output}\n[stderr]\n{error}".strip()
        return output or "(no output)"
    except TimeoutError as e:
        if process is not None:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        raise ToolError(f"command timed out after {timeout}s.") from e
    except asyncio.CancelledError:
        # Handle user cancellation (e.g., Ctrl-C)
        if process is not None:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        raise
