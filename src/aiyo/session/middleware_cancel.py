"""Cancellation middleware for cooperative cancellation."""

from .middleware_base import Middleware


class CancelMiddleware(Middleware):
    """Middleware that supports cancellation of long-running operations.

    The cancel() method can be called from another task (e.g., UI thread)
    to signal that the current operation should be cancelled. The middleware
    then checks this state at various hooks and raises CancelledError.
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        """Signal that the current operation should be cancelled."""
        self._cancelled = True

    def reset(self) -> None:
        """Reset cancellation state (for new turns)."""
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancelled

    def before_llm_call(self, messages):
        """Check cancellation before LLM call."""
        if self._cancelled:
            raise CancelledError()
        return messages

    def before_tool_call(self, tool_name, tool_args):
        """Check cancellation before tool execution."""
        if self._cancelled:
            raise CancelledError()
        return tool_name, tool_args


class CancelledError(Exception):
    """Raised when an operation is cancelled via CancelMiddleware."""

    pass
