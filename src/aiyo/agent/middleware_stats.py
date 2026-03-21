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
        self._tool_starts: dict[str, float] = {}
        self._chat_start: float | None = None

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Called before processing a user message."""
        if self._stats is not None:
            self._chat_start = time.time()
            self._stats.record_user_message()
        return user_message, tools

    def on_chat_end(self, response: str) -> str:
        """Called after receiving a response."""
        if self._stats is not None:
            self._stats.record_assistant_message()
            if self._chat_start is not None:
                duration_ms = (time.time() - self._chat_start) * 1000
                self._stats.total_duration_ms += duration_ms
                self._chat_start = None
        return response

    def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._stats is None:
            return messages
        self._llm_start = time.time()
        return messages

    def on_llm_response(
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

    def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        if self._stats is None:
            return tool_name, tool_id, tool_args
        self._tool_starts[tool_id] = time.time()
        return tool_name, tool_id, tool_args

    def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        if self._stats is None:
            return result
        started_at = self._tool_starts.pop(tool_id, None)
        if started_at is None:
            return result
        duration_ms = (time.time() - started_at) * 1000
        success = not isinstance(result, str) or not result.startswith("Error:")
        self._stats.record_tool_call(tool_name, duration_ms, success)
        return result
