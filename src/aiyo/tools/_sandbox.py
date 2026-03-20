"""Workspace sandbox helper."""

from pathlib import Path

from aiyo.config import settings


def safe_path(p: str) -> Path:
    """Resolve *p* relative to WORK_DIR and reject any path that escapes it.

    Supports symlinks inside the workspace (even if they point outside).
    Raises ValueError if the resolved path is outside the workspace.
    """
    workdir = settings.work_dir.resolve()
    target = workdir / p

    # Check if any path component inside workdir is a symlink
    # If so, allow it even if the symlink target is outside workdir
    try:
        rel_parts = target.relative_to(workdir).parts
    except ValueError:
        rel_parts = ()

    check_path = workdir
    for i, part in enumerate(rel_parts):
        check_path = check_path / part
        if check_path.is_symlink():
            # Found a symlink inside workdir, resolve it and append remaining parts
            resolved_link = check_path.resolve()
            remaining = rel_parts[i + 1 :]
            return resolved_link.joinpath(*remaining) if remaining else resolved_link

    # No symlinks in path (inside workdir), use normal resolution
    resolved = target.resolve()
    if not resolved.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace ({workdir}): {p!r}")
    return resolved
