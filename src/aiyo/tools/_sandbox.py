"""Workspace sandbox helper."""

from pathlib import Path

from aiyo.config import settings


def safe_path(p: str) -> Path:
    """Resolve *p* relative to WORK_DIR and reject any path that escapes it.

    Raises ValueError if the resolved path is outside the workspace.
    """
    workdir = settings.work_dir.resolve()
    resolved = (workdir / p).resolve()
    if not resolved.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace ({workdir}): {p!r}")
    return resolved
