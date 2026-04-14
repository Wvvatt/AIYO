"""Marker decorators for tool metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def _make_marker(
    name: str, doc: str
) -> tuple[Callable[[F], F], Callable[[Callable[..., Any] | None], bool]]:
    """Create a (decorator, checker) pair for a named boolean marker."""
    attr = f"__aiyo_{name}__"

    def marker(fn: F) -> F:
        setattr(fn, attr, True)
        return fn

    def has_marker(fn: Callable[..., Any] | None) -> bool:
        return bool(getattr(fn, attr, False))

    marker.__doc__ = doc
    marker.__name__ = name
    has_marker.__doc__ = f"Return True if fn was marked with @{name}."
    has_marker.__name__ = f"is_{name}"
    return marker, has_marker


gatherable, is_gatherable = _make_marker(
    "gatherable", "Mark a tool as safe to run concurrently via asyncio.gather."
)
not_for_planmode, is_not_for_planmode = _make_marker(
    "not_for_planmode", "Mark a tool as unavailable in PLAN mode."
)
