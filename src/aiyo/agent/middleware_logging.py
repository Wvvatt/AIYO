"""Logging middleware for debugging agent activity."""

import logging
from typing import Any

from .middleware import Middleware


class LoggingMiddleware(Middleware):
    """Structured and low-noise middleware logs."""

    _PREVIEW_LEN = 120

    def __init__(self) -> None:
        self.logger = logging.getLogger("aiyo.middleware.logging")

    @classmethod
    def _preview(cls, value: Any) -> str:
        text = str(value)
        if len(text) <= cls._PREVIEW_LEN:
            return text
        return text[: cls._PREVIEW_LEN] + "..."

    @staticmethod
    def _is_error_result(result: Any) -> bool:
        return isinstance(result, str) and result.startswith("Error:")

    @classmethod
    def _sanitize_args(cls, tool_args: dict[str, Any]) -> dict[str, Any]:
        # Keep log payload small and avoid leaking large/verbose values.
        return {k: cls._preview(v) for k, v in tool_args.items()}

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        self.logger.debug("chat.start tools=%d", len(tools))
        self.logger.debug("chat.input preview=%s", self._preview(user_message))
        return user_message, tools

    def on_chat_end(self, response: str) -> str:
        self.logger.debug("chat.end")
        self.logger.debug("chat.output preview=%s", self._preview(response))
        return response

    def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msg_count = len(messages)
        token_count = sum(len(str(m.get("content", ""))) for m in messages) // 4
        self.logger.debug("llm.call messages=%d approx_tokens=%d", msg_count, token_count)
        return messages

    def on_llm_response(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        msg = response.choices[0].message if hasattr(response, "choices") else response
        tool_calls = len(msg.tool_calls) if hasattr(msg, "tool_calls") and msg.tool_calls else 0
        self.logger.debug(
            "llm.response tool_calls=%d content_chars=%d", tool_calls, len(msg.content or "")
        )
        return response

    def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        self.logger.debug(
            "tool.start name=%s id=%s args=%s",
            tool_name,
            tool_id,
            self._sanitize_args(tool_args),
        )
        return tool_name, tool_id, tool_args

    def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
        tool_error: Exception | None,
        result: Any,
    ) -> Any:
        status = "error" if (tool_error is not None or self._is_error_result(result)) else "ok"
        self.logger.debug(
            "tool.end name=%s id=%s status=%s error=%s result=%s",
            tool_name,
            tool_id,
            status,
            type(tool_error).__name__ if tool_error is not None else "-",
            self._preview(result),
        )
        return result

    def on_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        self.logger.debug(
            "error in %s: %s",
            context.get("stage", "unknown"),
            error,
            exc_info=True,
        )
