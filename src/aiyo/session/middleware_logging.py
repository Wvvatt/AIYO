"""Logging middleware for debugging agent activity."""

from typing import Any

from .exceptions import AgentError
from .middleware_base import Middleware


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

    def _format_tool_name(self, tool_name: str) -> str:
        """Convert snake_case to CamelCase (e.g., read_file -> ReadFile)."""
        parts = tool_name.split("_")
        return "".join(part.capitalize() for part in parts if part)

    def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
    ) -> Any:
        display_name = self._format_tool_name(tool_name)

        if tool_name == "todo":
            print(f"\033[36m{display_name}\033[0m\n{result}")
        elif tool_name == "think":
            thought = tool_args.get("thought", "")
            print(f"\033[36m{display_name}\033[0m\n{thought}")
        elif tool_name in ("read_file", "write_file", "str_replace_file"):
            path = tool_args.get("path", "")
            print(f"\033[36m{display_name}\033[0m {path}")
        elif tool_name == "glob_files":
            pattern = tool_args.get("pattern", "")
            print(f"\033[36m{display_name}\033[0m {pattern}")
        elif tool_name == "list_directory":
            path = tool_args.get("relative_path", ".")
            print(f"\033[36m{display_name}\033[0m {path}")
        else:
            print(f"\033[36m{display_name}\033[0m")

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
