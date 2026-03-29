"""Path resolution helper."""

from pathlib import Path

from aiyo.config import settings


def safe_path(p: str, **_kwargs) -> Path:
    """Resolve *p* relative to WORK_DIR. Absolute paths are used as-is."""
    workdir = settings.work_dir.resolve()
    return (workdir / p).resolve()
