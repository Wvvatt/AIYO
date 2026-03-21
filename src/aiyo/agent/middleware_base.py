"""Base middleware classes and chain management."""

import inspect
from typing import Any

# Hooks that thread their return value back as the first positional arg
_CHAIN_FIRST: frozenset[str] = frozenset({"on_chat_end", "on_iteration_start"})
# Hooks that thread their return value back as the last positional arg
_CHAIN_LAST: frozenset[str] = frozenset({"on_llm_response", "on_tool_call_end"})
# Hooks that return a tuple replacing ALL positional args
_CHAIN_ALL: frozenset[str] = frozenset({"on_chat_start", "on_tool_call_start"})


class Middleware:
    """Base class for middleware.

    Middleware can intercept and modify agent behavior at various points.
    Override specific methods to add custom behavior.
    """

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Called before processing a user message.

        Args:
            user_message: The user's input message.
            tools: List of available tools for this chat.

        Returns:
            Tuple of (user_message, tools), potentially modified.
        """
        return user_message, tools

    def on_chat_end(self, response: str) -> str:
        """Called after receiving a response.

        Returns:
            Potentially modified response.
        """
        return response

    def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Called before each iteration (LLM API call).

        Returns:
            Potentially modified messages.
        """
        return messages

    def on_llm_response(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        """Called after receiving LLM response.

        Returns:
            Potentially modified response.
        """
        return response

    def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        """Called before each tool execution.

        Returns:
            Tuple of (tool_name, tool_id, tool_args), potentially modified.
        """
        return tool_name, tool_id, tool_args

    def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Called after each tool execution.

        Returns:
            Potentially modified result.
        """
        return result

    def on_iteration_end(
        self,
        iteration: int,
        messages: list[dict[str, Any]],
    ) -> None:
        """Called at the end of each agent iteration."""
        pass

    def on_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        """Called when an error occurs."""
        pass


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

    async def execute_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> Any:
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
                    if inspect.iscoroutine(result):
                        result = await result
                    if hook_name in _CHAIN_ALL:
                        current = list(result)
                    elif hook_name in _CHAIN_LAST:
                        current[-1] = result
                    else:  # _CHAIN_FIRST
                        current[0] = result
                else:
                    result = hook(*current, **kwargs)
                    if inspect.iscoroutine(result):
                        await result
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
