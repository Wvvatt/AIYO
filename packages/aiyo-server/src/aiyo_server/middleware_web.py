"""WebSocket streaming middleware for AIYO agent."""

import asyncio
from typing import Any

from aiyo.agent.middleware import Middleware
from fastapi import WebSocket


class WebStreamMiddleware(Middleware):
    """Middleware that streams agent events to WebSocket client."""

    def __init__(self):
        self.ws: WebSocket | None = None
        self._tool_counter = 0
        self._current_tool_id: str | None = None

    def bind(self, ws: WebSocket):
        """Bind to a WebSocket connection."""
        self.ws = ws
        self._tool_counter = 0

    def unbind(self):
        """Unbind from WebSocket connection."""
        self.ws = None

    async def _emit(self, data: dict[str, Any]):
        """Emit event to WebSocket client."""
        if self.ws:
            await self.ws.send_json(data)

    async def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Called before processing a user message."""
        return user_message, tools

    async def on_chat_end(self, response: str) -> str:
        """Called after receiving a response."""
        await self._emit({"type": "chat_end", "content": response})
        return response

    async def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Called before each iteration (LLM API call)."""
        # Emit thinking indicator
        asyncio.create_task(self._emit({"type": "thinking"}))
        return messages

    async def on_llm_response(self, messages: list[dict[str, Any]], response: Any) -> Any:
        """Called after receiving LLM response."""
        return response

    async def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        """Called before each tool execution."""
        self._tool_counter += 1
        self._current_tool_id = f"tool_{self._tool_counter}"

        # Create summary from arguments
        summary = self._create_summary(tool_name, tool_args)

        await self._emit(
            {
                "type": "tool_start",
                "tool": tool_name,
                "id": self._current_tool_id,
                "summary": summary,
            }
        )

        return tool_name, tool_id, tool_args

    async def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
        tool_error: Exception | None,
        result: Any,
    ) -> Any:
        """Called after each tool execution."""
        await self._emit(
            {
                "type": "tool_end",
                "tool": tool_name,
                "id": self._current_tool_id or tool_id,
                "error": str(tool_error) if tool_error else None,
            }
        )
        return result

    async def on_iteration_end(self, iteration: int, messages: list[dict[str, Any]]) -> None:
        """Called at the end of each agent iteration."""

    async def on_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Called when an error occurs."""
        asyncio.create_task(self._emit({"type": "error", "message": str(error)}))

    def _create_summary(self, tool: str, arguments: dict[str, Any]) -> str:
        """Create a human-readable summary of tool call."""
        if tool == "read_file":
            path = arguments.get("path", "unknown")
            return f"Reading {path}"
        elif tool == "write_file":
            path = arguments.get("path", "unknown")
            return f"Writing {path}"
        elif tool == "str_replace":
            path = arguments.get("path", "unknown")
            return f"Editing {path}"
        elif tool == "shell":
            cmd = arguments.get("command", "")[:50]
            return f"$ {cmd}"
        elif tool == "search":
            pattern = arguments.get("pattern", "")
            return f"Searching '{pattern}'"
        elif tool == "kb_search":
            query = arguments.get("query", "")
            return f"Knowledge: '{query}'"
        else:
            # Generic summary
            args_str = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:2])
            return f"{tool}({args_str})"
