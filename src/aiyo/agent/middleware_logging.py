"""Logging middleware for debugging agent activity."""

import logging
from typing import Any

from .exceptions import AgentError
from .middleware_base import Middleware


class LoggingMiddleware(Middleware):
    """Middleware that logs agent activity with clear severity levels.

    Level policy:
    - DEBUG: payload previews, detailed internals
    - INFO: major workflow milestones
    - WARNING: expected but notable issues (tool/runtime guardrails)
    - ERROR: failures that should be investigated
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("aiyo.middleware.logging")

    def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        self.logger.info("chat started: %d tools available", len(tools))
        self.logger.debug(
            "user message preview: %s",
            user_message[:100] + "..." if len(user_message) > 100 else user_message,
        )
        return user_message, tools

    def on_chat_end(self, response: str) -> str:
        self.logger.info("chat completed")
        self.logger.debug(
            "agent response preview: %s",
            response[:100] + "..." if len(response) > 100 else response,
        )
        return response

    def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msg_count = len(messages)
        token_count = sum(len(str(m.get("content", ""))) for m in messages) // 4
        self.logger.debug("calling LLM: %d messages (~%d tokens)", msg_count, token_count)
        return messages

    def on_llm_response(
        self,
        messages: list[dict[str, Any]],
        response: Any,
    ) -> Any:
        msg = response.choices[0].message if hasattr(response, "choices") else response
        tool_calls = len(msg.tool_calls) if hasattr(msg, "tool_calls") and msg.tool_calls else 0
        self.logger.info(
            "LLM response received: %d tool calls, %d chars content",
            tool_calls,
            len(msg.content or ""),
        )
        return response

    def on_tool_call_start(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        self.logger.info("tool call started: %s", tool_name)
        self.logger.debug("tool args (%s): %s", tool_name, tool_args)
        return tool_name, tool_args

    def on_tool_call_end(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        result_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
        if isinstance(result, str) and result.startswith("Error:"):
            self.logger.warning("tool call failed: %s", tool_name)
            self.logger.debug("tool result (%s): %s", tool_name, result_preview)
        else:
            self.logger.info("tool call completed: %s", tool_name)
            self.logger.debug("tool result (%s): %s", tool_name, result_preview)
        return result

    def on_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        log_fn = self.logger.warning if isinstance(error, AgentError) else self.logger.error
        log_fn(
            "error in %s: %s",
            context.get("stage", "unknown"),
            error,
            exc_info=not isinstance(error, AgentError),
        )
