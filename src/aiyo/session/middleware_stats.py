"""Statistics tracking middleware."""

import time
from typing import TYPE_CHECKING, Any

from .middleware_base import Middleware

if TYPE_CHECKING:
    from .stats import SessionStats


class StatsMiddleware(Middleware):
    """Middleware that tracks token usage, timing, and tool call statistics."""

    def __init__(self, stats: "SessionStats | None" = None) -> None:
        self._stats = stats  # None means stats are disabled
        self._llm_start: float | None = None
        self._tool_start: float | None = None
        self._chat_start: float | None = None

    def before_chat(self, user_message: str) -> str:
        """Called before processing a user message."""
        if self._stats is not None:
            self._chat_start = time.time()
            self._stats.record_user_message()
        return user_message

    def after_chat(self, response: str) -> str:
        """Called after receiving a response."""
        if self._stats is not None:
            self._stats.record_assistant_message()
            if self._chat_start is not None:
                duration_ms = (time.time() - self._chat_start) * 1000
                self._stats.total_duration_ms += duration_ms
                self._chat_start = None
        return response

    def before_llm_call(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._stats is None:
            return messages
        self._llm_start = time.time()
        return messages

    def after_llm_call(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        if self._stats is None or self._llm_start is None:
            return response
        duration_ms = (time.time() - self._llm_start) * 1000
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage"):
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0
        self._stats.record_llm_call(input_tokens, output_tokens, duration_ms)
        self._llm_start = None
        return response

    def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if self._stats is None:
            return tool_name, tool_args
        self._tool_start = time.time()
        return tool_name, tool_args

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        if self._stats is None or self._tool_start is None:
            return result
        duration_ms = (time.time() - self._tool_start) * 1000
        success = not isinstance(result, str) or not result.startswith("Error:")
        self._stats.record_tool_call(tool_name, duration_ms, success)
        self._tool_start = None
        return result
