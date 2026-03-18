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
    """
    timeout = max(1, min(timeout, 300))
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
        if error:
            output = f"{output}\n[stderr]\n{error}".strip()
        return output or "(no output)"
    except TimeoutError as e:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise ToolError(f"command timed out after {timeout}s.") from e
