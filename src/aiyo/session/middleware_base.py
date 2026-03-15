"""Base middleware classes and chain management."""

from typing import Any

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
