"""Middleware system for the AIYO agent.

Allows injecting custom logic at various points in the agent lifecycle.
"""

import time
from typing import Any

from .exceptions import AgentError

__all__ = [
    "Middleware",
    "LoggingMiddleware",
    "StatsMiddleware",
    "TodoDisplayMiddleware",
    "MiddlewareChain",
]

# Hooks that thread their return value back as the first positional arg
_CHAIN_FIRST: frozenset[str] = frozenset({"before_chat", "after_chat", "before_llm_call"})
# Hooks that thread their return value back as the last positional arg
_CHAIN_LAST: frozenset[str] = frozenset({"after_llm_call", "after_tool_call"})
# Hooks that return a tuple replacing ALL positional args
_CHAIN_ALL: frozenset[str] = frozenset({"before_tool_call"})


class Middleware:
    """Base class for middleware.

    Middleware can intercept and modify agent behavior at various points.
    Override specific methods to add custom behavior.
    """

    def before_chat(self, user_message: str) -> str:
        """Called before processing a user message.

        Returns:
            Potentially modified user message.
        """
        return user_message

    def after_chat(self, response: str) -> str:
        """Called after receiving a response.

        Returns:
            Potentially modified response.
        """
        return response

    def before_llm_call(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Called before each LLM API call.

        Returns:
            Potentially modified messages.
        """
        return messages

    def after_llm_call(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        """Called after each LLM API call.

        Returns:
            Potentially modified response.
        """
        return response

    def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Called before each tool execution.

        Returns:
            Tuple of (tool_name, tool_args), potentially modified.
        """
        return tool_name, tool_args

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Called after each tool execution.

        Returns:
            Potentially modified result.
        """
        return result

    def on_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        """Called when an error occurs."""
        pass

    def on_iteration_end(
        self,
        iteration: int,
        messages: list[dict[str, Any]],
    ) -> None:
        """Called at the end of each agent iteration."""
        pass


class LoggingMiddleware(Middleware):
    """Middleware that logs agent activity at DEBUG level."""

    def __init__(self) -> None:
        import logging

        self.logger = logging.getLogger("aiyo.middleware.logging")

    def before_chat(self, user_message: str) -> str:
        self.logger.debug(
            "📥 User message: %s",
            user_message[:100] + "..." if len(user_message) > 100 else user_message,
        )
        return user_message

    def after_chat(self, response: str) -> str:
        self.logger.debug(
            "📤 Agent response: %s",
            response[:100] + "..." if len(response) > 100 else response,
        )
        return response

    def before_llm_call(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msg_count = len(messages)
        token_count = sum(len(str(m.get("content", ""))) for m in messages) // 4
        self.logger.debug("🤖 Calling LLM with %d messages (~%d tokens)", msg_count, token_count)
        return messages

    def after_llm_call(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        msg = response.choices[0].message if hasattr(response, "choices") else response
        tool_calls = len(msg.tool_calls) if hasattr(msg, "tool_calls") and msg.tool_calls else 0
        self.logger.debug(
            "✅ LLM response received: %d tool calls, %d chars content",
            tool_calls,
            len(msg.content or ""),
        )
        return response

    def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        self.logger.debug("🔧 Calling tool: %s with args: %s", tool_name, tool_args)
        return tool_name, tool_args

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        result_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
        self.logger.debug("✓ Tool %s returned: %s", tool_name, result_preview)
        return result

    def on_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        self.logger.debug(
            "❌ Error in %s: %s",
            context.get("stage", "unknown"),
            error,
            exc_info=not isinstance(error, AgentError),
        )


class StatsMiddleware(Middleware):
    """Middleware that tracks token usage, timing, and tool call statistics."""

    def __init__(self) -> None:
        from .stats import AgentStats

        self.stats = AgentStats()
        self._llm_start: float | None = None
        self._tool_start: float | None = None

    def before_llm_call(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._llm_start = time.time()
        return messages

    def after_llm_call(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        if self._llm_start is not None:
            duration_ms = (time.time() - self._llm_start) * 1000
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage"):
                input_tokens = response.usage.prompt_tokens or 0
                output_tokens = response.usage.completion_tokens or 0
            self.stats.record_llm_call(input_tokens, output_tokens, duration_ms)
            self._llm_start = None
        return response

    def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        self._tool_start = time.time()
        return tool_name, tool_args

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        if self._tool_start is not None:
            duration_ms = (time.time() - self._tool_start) * 1000
            success = not isinstance(result, str) or not result.startswith("Error:")
            self.stats.record_tool_call(tool_name, duration_ms, success)
            self._tool_start = None
        return result


class TodoDisplayMiddleware(Middleware):
    """Middleware that prints todo list updates to the terminal."""

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        if tool_name == "todo":
            print(result)
        return result


class MiddlewareChain:
    """Manages a chain of middleware executed in insertion order."""

    def __init__(self) -> None:
        self._middleware: list[Middleware] = []

    def add(self, middleware: Middleware) -> "MiddlewareChain":
        """Add a middleware to the chain."""
        self._middleware.append(middleware)
        return self

    def remove(self, middleware: Middleware) -> None:
        """Remove a middleware from the chain."""
        if middleware in self._middleware:
            self._middleware.remove(middleware)

    def execute_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a hook across all middleware, threading results between them.

        Chaining rules (determined by hook signature):
          - _CHAIN_FIRST hooks  : return value replaces the first positional arg
          - _CHAIN_LAST hooks   : return value replaces the last positional arg
          - _CHAIN_ALL hooks    : returned tuple replaces all positional args
          - all other hooks     : fire-and-forget (return value ignored)
        """
        is_modifying = hook_name in _CHAIN_FIRST | _CHAIN_LAST | _CHAIN_ALL
        current: list[Any] = list(args)

        for mw in self._middleware:
            hook = getattr(mw, hook_name, None)
            if hook is None:
                continue
            try:
                if is_modifying:
                    result = hook(*current, **kwargs)
                    if hook_name in _CHAIN_ALL:
                        current = list(result)
                    elif hook_name in _CHAIN_LAST:
                        current[-1] = result
                    else:  # _CHAIN_FIRST
                        current[0] = result
                else:
                    hook(*current, **kwargs)
            except Exception as e:
                for mw_err in self._middleware:
                    try:
                        mw_err.on_error(e, {"hook": hook_name})
                    except Exception:
                        pass
                raise

        if not is_modifying:
            return None
        if hook_name in _CHAIN_ALL:
            return tuple(current)
        return current[-1] if hook_name in _CHAIN_LAST else current[0]

    def __iter__(self):
        return iter(self._middleware)

    def __len__(self) -> int:
        return len(self._middleware)
