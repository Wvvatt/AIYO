"""Workspace sandbox helper."""

from pathlib import Path

from aiyo.config import settings


def safe_path(p: str, *, allow_symlink_escape: bool = False) -> Path:
    """Resolve *p* relative to WORK_DIR and reject any path that escapes it.

    By default, symlinks that resolve outside WORK_DIR are rejected.
    Set allow_symlink_escape=True to allow them explicitly.
    Raises ValueError if the resolved path is outside the workspace.
    """
    workdir = settings.work_dir.resolve()
    target = workdir / p

    resolved = target.resolve()
    if resolved.is_relative_to(workdir):
        return resolved

    if allow_symlink_escape:
        # Explicit opt-in for callers that intentionally want to follow
        # workspace-internal symlinks to external locations.
        return resolved

    try:
        target.relative_to(workdir)
        is_internal_link_escape = True
    except ValueError:
        is_internal_link_escape = False

    if is_internal_link_escape:
        raise ValueError(
            f"Path escapes workspace via symlink ({workdir}): {p!r}. "
            "External symlink targets are blocked by default."
        )
    if not resolved.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace ({workdir}): {p!r}")
    return resolved
