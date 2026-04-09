"""Base middleware classes and chain management.

Each hook receives a single mutable context object. Middleware mutates
fields on the context in place; there is no return-value threading.
Adding or removing a field on a context never changes the hook signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ===== Hook contexts =====


@dataclass(slots=True)
class ChatStartContext:
    """Context for `on_chat_start` — fired before a user message is processed."""

    user_message: str
    tools: list[Any]


@dataclass(slots=True)
class ChatEndContext:
    """Context for `on_chat_end` — fired after the final response is produced."""

    response: str


@dataclass(slots=True)
class IterationStartContext:
    """Context for `on_iteration_start` — fired before each LLM call."""

    messages: list[dict[str, Any]]


@dataclass(slots=True)
class LLMResponseContext:
    """Context for `on_llm_response` — fired after each LLM call returns."""

    messages: list[dict[str, Any]]
    response: Any


@dataclass(slots=True)
class ToolCallStartContext:
    """Context for `on_tool_call_start` — fired before each tool is executed.

    Middleware can mutate `tool_name`, `tool_id`, `tool_args`, or `summary`
    in place. Raise `ToolBlockedError` to abort the call (the error's reason
    becomes the tool result).
    """

    tool_name: str
    tool_id: str
    tool_args: dict[str, Any]
    summary: str = ""


@dataclass(slots=True)
class ToolCallEndContext:
    """Context for `on_tool_call_end` — fired after each tool finishes.

    `tool_error` is the exception raised by the tool (if any). Middleware
    can replace `result` to rewrite what the LLM sees.
    """

    tool_name: str
    tool_id: str
    tool_args: dict[str, Any]
    tool_error: Exception | None
    result: Any


@dataclass(slots=True)
class IterationEndContext:
    """Context for `on_iteration_end` — fired after a complete iteration."""

    iteration: int
    messages: list[dict[str, Any]]


@dataclass(slots=True)
class ErrorContext:
    """Context for `on_error` — fired when a middleware hook raises."""

    error: Exception
    context: dict[str, Any] = field(default_factory=dict)


# ===== Middleware base class =====


class Middleware:
    """Base class for middleware.

    Override the hooks you care about. Each hook receives a single mutable
    context object — read or modify its fields in place. Hooks return None;
    do not return a value.
    """

    async def on_chat_start(self, ctx: ChatStartContext) -> None:
        """Called before processing a user message."""

    async def on_chat_end(self, ctx: ChatEndContext) -> None:
        """Called after the final response is produced."""

    async def on_iteration_start(self, ctx: IterationStartContext) -> None:
        """Called before each iteration (LLM API call)."""

    async def on_llm_response(self, ctx: LLMResponseContext) -> None:
        """Called after receiving an LLM response."""

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        """Called before each tool execution.

        Raise `ToolBlockedError` to abort the call; the error's `reason`
        will be returned as the tool result.
        """

    async def on_tool_call_end(self, ctx: ToolCallEndContext) -> None:
        """Called after each tool execution."""

    async def on_iteration_end(self, ctx: IterationEndContext) -> None:
        """Called at the end of each agent iteration."""

    async def on_error(self, ctx: ErrorContext) -> None:
        """Called when a middleware hook raises an exception."""


# ===== Chain =====


class MiddlewareChain:
    """Manages a chain of middleware executed in insertion order."""

    def __init__(self) -> None:
        self._middleware: list[Middleware] = []

    def add(self, middleware: Middleware) -> MiddlewareChain:
        """Add a middleware to the chain."""
        self._middleware.append(middleware)
        return self

    def remove(self, middleware: Middleware) -> None:
        """Remove a middleware from the chain."""
        if middleware in self._middleware:
            self._middleware.remove(middleware)

    async def execute_hook(self, hook_name: str, ctx: Any) -> Any:
        """Run a hook across every middleware in insertion order.

        Each middleware receives the same `ctx` object and may mutate its
        fields in place. The (potentially mutated) `ctx` is returned so the
        caller can read updated fields.

        If a hook raises, every middleware's `on_error` is invoked (errors
        from `on_error` itself are swallowed) and the original exception is
        re-raised.
        """
        for mw in self._middleware:
            hook = getattr(mw, hook_name, None)
            if hook is None:
                continue
            try:
                await hook(ctx)
            except Exception as exc:
                err_ctx = ErrorContext(error=exc, context={"hook": hook_name})
                for mw_err in self._middleware:
                    try:
                        await mw_err.on_error(err_ctx)
                    except Exception:
                        pass
                raise
        return ctx

    def __iter__(self):
        return iter(self._middleware)

    def __len__(self) -> int:
        return len(self._middleware)
