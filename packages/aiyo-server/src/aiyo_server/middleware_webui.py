"""WebSocket streaming middleware for AIYO agent."""

import asyncio
from typing import Any

from aiyo.agent.middleware import Middleware
from aiyo.agent.stats import SessionStats
from ext.tools.confluence_tools import health as confluence_health
from ext.tools.gerrit_tools import health as gerrit_health
from ext.tools.jira_tools import health as jira_health
from fastapi import WebSocket


class WebUiDisplayMiddleware(Middleware):
    """Middleware that streams agent events to WebSocket client."""

    def __init__(self):
        self.ws: WebSocket | None = None
        # Map tool_id → pending future, one per concurrent ask_user call
        self._user_response_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._model_name: str = ""
        self._stats: SessionStats | None = None

    def bind(self, ws: WebSocket, model_name: str = "", stats: SessionStats | None = None):
        """Bind to a WebSocket connection."""
        self.ws = ws
        self._model_name = model_name
        self._stats = stats

    def unbind(self):
        """Unbind from WebSocket connection."""
        self.ws = None
        for future in self._user_response_futures.values():
            if not future.done():
                future.cancel()
        self._user_response_futures.clear()

    async def _emit(self, data: dict[str, Any]):
        """Emit event to WebSocket client."""
        if self.ws:
            await self.ws.send_json(data)

    async def _emit_status(self) -> None:
        """Push current status bar data to the client."""
        stats = self._stats
        await self._emit(
            {
                "type": "status",
                "model": self._model_name,
                "tokens": {
                    "input": stats.total_input_tokens if stats else 0,
                    "output": stats.total_output_tokens if stats else 0,
                    "total": stats.total_tokens if stats else 0,
                },
                "turns": stats.total_user_messages if stats else 0,
            }
        )

    async def check_services_health(self) -> dict[str, str]:
        """Check health of all external services."""
        # Run health checks in parallel
        results = await asyncio.gather(
            asyncio.to_thread(jira_health),
            asyncio.to_thread(confluence_health),
            asyncio.to_thread(gerrit_health),
            return_exceptions=True,
        )

        services = {}
        name_mapping = {
            "jira_cli": "jira",
            "confluence_cli": "confluence",
            "gerrit_cli": "gerrit",
        }
        for result in results:
            if isinstance(result, Exception):
                continue
            internal_name = result.get("name", "unknown")
            public_name = name_mapping.get(internal_name, internal_name)
            status = result.get("status", "error")
            # Map status to simple online/offline
            services[public_name] = "online" if status == "ok" else "offline"

        return services

    def set_user_response(self, answers: dict[str, Any], ask_user_id: str | None = None) -> None:
        """Deliver the user's answer to a pending ask_user call.

        Expected format from frontend:
            {
                "answers": {question_text: selected_label_or_text},
                "annotations": {question_text: {"preview": ..., "notes": None}},
                "metadata": {"source": "ask_user"}
            }

        Args:
            answers: The answer payload from the frontend.
            ask_user_id: The display_id of the ask_user call to respond to.
                         If None, resolves the first pending future (legacy fallback).
        """
        if ask_user_id and ask_user_id in self._user_response_futures:
            future = self._user_response_futures[ask_user_id]
            if not future.done():
                future.set_result(answers)
        elif ask_user_id is None:
            # Fallback: resolve first pending future
            for future in self._user_response_futures.values():
                if not future.done():
                    future.set_result(answers)
                    break

    async def on_chat_start(self, user_message: str, tools: list[Any]) -> tuple[str, list[Any]]:
        """Called before processing a user message."""
        return user_message, tools

    async def on_chat_end(self, response: str) -> str:
        """Called after receiving a response."""
        await self._emit({"type": "chat_end", "content": response})
        await self._emit_status()
        return response

    async def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Called before each iteration (LLM API call)."""
        await self._emit({"type": "thinking"})
        return messages

    async def on_llm_response(self, messages: list[dict[str, Any]], response: Any) -> Any:
        """Called after receiving LLM response."""
        await self._emit_status()
        return response

    async def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        """Called before each tool execution."""
        summary = self._create_summary(tool_name, tool_args)
        msg: dict[str, Any] = {
            "type": "tool_start",
            "tool": tool_name,
            "id": tool_id,
            "summary": summary,
        }
        if tool_name == "think":
            msg["thought"] = tool_args.get("thought", "")
        await self._emit(msg)

        if tool_name == "ask_user":
            future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
            self._user_response_futures[tool_id] = future
            await self._emit(
                {
                    "type": "ask_user",
                    "id": tool_id,
                    "questions": tool_args.get("questions", []),
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
        if tool_name == "ask_user":
            future = self._user_response_futures.get(tool_id)
            if future is not None:
                result = await future
                del self._user_response_futures[tool_id]

        msg: dict[str, Any] = {
            "type": "tool_end",
            "tool": tool_name,
            "id": tool_id,
            "error": str(tool_error) if tool_error else None,
        }
        _TASK_TOOLS = {"task_create", "task_update", "task_list", "task_delete"}
        if tool_name in _TASK_TOOLS and not tool_error and isinstance(result, dict):
            msg["task_result"] = result
        await self._emit(msg)
        return result

    async def on_iteration_end(self, iteration: int, messages: list[dict[str, Any]]) -> None:
        """Called at the end of each agent iteration."""

    async def on_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Called when an error occurs."""
        await self._emit({"type": "error", "message": str(error)})

    @staticmethod
    def _format_name(tool_name: str) -> str:
        return "".join(p.capitalize() for p in tool_name.split("_"))

    def _create_summary(self, tool: str, arguments: dict[str, Any]) -> str:
        """Create a human-readable summary of tool call."""
        name = self._format_name(tool)
        match tool:
            case "read_file" | "write_file" | "edit_file" | "read_image" | "read_pdf":
                return f"{name} {arguments.get('path', '')}"
            case "list_directory":
                return f"{name} {arguments.get('path', '.')}"
            case "glob_files":
                return f"{name} {arguments.get('pattern', '')}"
            case "grep_files":
                pattern = arguments.get("pattern", "")
                path = arguments.get("path", ".")
                return f"{name} {pattern!r} in {path}"
            case "shell":
                cmd = arguments.get("command", "")[:60]
                return f"{name} {cmd}"
            case "fetch_url":
                return f"{name} {arguments.get('url', '')}"
            case "load_skill":
                return f"{name} {arguments.get('name', '')}"
            case "load_skill_resource":
                skill = arguments.get("skill_name", "")
                resource = arguments.get("resource_path", "")
                return f"{name} {skill}/{resource}"
            case "think":
                thought = arguments.get("thought", "")[:60]
                return f"{name} {thought}"
            case "ask_user":
                questions = arguments.get("questions", [])
                if questions:
                    first = questions[0]
                    q_text = first.get("question", "") if isinstance(first, dict) else str(first)
                    return f"{name} {q_text[:60]}"
                return name
            case "task_create":
                tasks = arguments.get("tasks", [])
                if isinstance(tasks, list) and tasks:
                    title = str(tasks[0].get("title", ""))
                    summary = f"{len(tasks)} task(s)"
                    if title:
                        summary = f"{summary}: {title}"
                    return f"{name} {summary}"
                return name
            case "task_get" | "task_delete" | "task_update":
                return f"{name} {arguments.get('task_id', '')}"
            case _:
                return name
