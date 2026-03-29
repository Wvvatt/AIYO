"""Middleware for normalizing weak-model tool arguments."""

from __future__ import annotations

import json
from collections.abc import Callable
from inspect import _empty, signature
from types import UnionType
from typing import Any, Union, get_args, get_origin

from .middleware import Middleware


def _expects_list(annotation: Any) -> bool:
    """Return True when the annotation is (or includes) a list type."""
    if annotation is _empty or annotation is Any:
        return False

    origin = get_origin(annotation)
    if origin is list:
        return True

    if origin in (UnionType, Union):
        return any(_expects_list(arg) for arg in get_args(annotation))

    return False


def _coerce_list_like(value: Any) -> Any:
    """Best-effort coercion for weak-model tool args: str -> list[str]."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return []

    # First try to parse JSON arrays represented as strings.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Fall back to common weak-model formats: comma/newline separated strings.
    if "," in stripped:
        return [part.strip() for part in stripped.split(",") if part.strip()]
    if "\n" in stripped:
        return [part.strip() for part in stripped.splitlines() if part.strip()]
    return [stripped]


class ArgNormalizationMiddleware(Middleware):
    """Normalize tool args before execution based on tool annotations."""

    def __init__(self, tool_map: dict[str, Callable[..., Any]]) -> None:
        self._tool_map = tool_map

    def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        fn = self._tool_map.get(tool_name)
        if fn is None:
            return tool_name, tool_id, tool_args

        try:
            sig = signature(fn)
        except Exception:
            return tool_name, tool_id, tool_args

        normalized = dict(tool_args)
        for param_name, param in sig.parameters.items():
            if param_name not in normalized:
                continue
            if _expects_list(param.annotation):
                normalized[param_name] = _coerce_list_like(normalized[param_name])

        return tool_name, tool_id, normalized
