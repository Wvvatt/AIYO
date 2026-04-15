"""Decorators and helpers for tool metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
ToolSummaryFn = Callable[[dict[str, Any]], str]
ToolHealthFn = Callable[[], dict[str, Any]]


@dataclass(slots=True)
class ToolMeta:
    """Runtime metadata attached to a tool function."""

    gatherable: bool = False
    not_for_planmode: bool = False
    summary: ToolSummaryFn | None = None
    health_check: ToolHealthFn | None = None


class tool:
    def __init__(
        self,
        *,
        gatherable: bool = False,
        not_for_planmode: bool = False,
        summary: ToolSummaryFn | None = None,
        health_check: ToolHealthFn | None = None,
    ) -> None:
        self.meta = ToolMeta(
            gatherable=gatherable,
            not_for_planmode=not_for_planmode,
            summary=summary,
            health_check=health_check,
        )

    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        if hasattr(fn, "__aiyo_tool_meta__"):
            raise TypeError(f"{fn.__name__} already has @tool metadata")
        setattr(fn, "__aiyo_tool_meta__", self.meta)
        return fn


def get_tool_meta(fn: Callable[..., Any] | None) -> ToolMeta:
    """Return normalized metadata for a tool function."""
    if fn is None:
        return ToolMeta()
    meta = getattr(fn, "__aiyo_tool_meta__", None)
    if isinstance(meta, ToolMeta):
        return meta
    return ToolMeta()


def get_summary(fn: Callable[..., Any] | None, tool_args: dict[str, Any]) -> str:
    """Return the summary for a tool call."""
    summary_fn = get_tool_meta(fn).summary
    if summary_fn is None:
        return ""
    return summary_fn(tool_args)


def health_check(fn: Callable[..., Any] | None) -> dict[str, Any] | None:
    """Run and return the health check result for a tool, if any."""
    health_fn = get_tool_meta(fn).health_check
    if health_fn is None:
        return None
    return health_fn()


def is_gatherable(fn: Callable[..., Any] | None) -> bool:
    """Return True if fn can be executed concurrently."""
    return get_tool_meta(fn).gatherable


def is_not_for_planmode(fn: Callable[..., Any] | None) -> bool:
    """Return True if fn is unavailable in PLAN mode."""
    return get_tool_meta(fn).not_for_planmode


__all__ = [
    "ToolMeta",
    "ToolSummaryFn",
    "ToolHealthFn",
    "tool",
    "get_tool_meta",
    "get_summary",
    "health_check",
    "is_gatherable",
    "is_not_for_planmode",
]
