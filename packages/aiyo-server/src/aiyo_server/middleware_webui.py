"""WebSocket streaming middleware for AIYO agent."""

import asyncio
from typing import Any

from aiyo.agent.middleware import (
    ChatEndContext,
    ChatStartContext,
    ErrorContext,
    IterationEndContext,
    IterationStartContext,
    LLMResponseContext,
    Middleware,
    ToolCallEndContext,
    ToolCallStartContext,
)
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
            jira_health(),
            confluence_health(),
            gerrit_health(),
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

    async def on_chat_start(self, ctx: ChatStartContext) -> None:
        """Called before processing a user message."""

    async def on_chat_end(self, ctx: ChatEndContext) -> None:
        """Called after receiving a response."""
        await self._emit({"type": "chat_end", "content": ctx.response})
        await self._emit_status()

    async def on_iteration_start(self, ctx: IterationStartContext) -> None:
        """Called before each iteration (LLM API call)."""
        await self._emit({"type": "thinking"})

    async def on_llm_response(self, ctx: LLMResponseContext) -> None:
        """Called after receiving LLM response."""
        msg = ctx.response.choices[0].message
        if msg.reasoning and msg.reasoning.content:
            await self._emit({"type": "reasoning", "content": msg.reasoning.content})
        content = " ".join((msg.content or "").split())
        if content and msg.tool_calls:
            await self._emit({"type": "reasoning", "content": content})
        await self._emit_status()

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        """Called before each tool execution."""
        await self._emit(
            {
                "type": "tool_start",
                "tool": ctx.tool_name,
                "id": ctx.tool_id,
                "summary": ctx.summary,
                "args": ctx.tool_args,
            }
        )

    async def on_tool_call_end(self, ctx: ToolCallEndContext) -> None:
        """Called after each tool execution."""
        if ctx.tool_name == "ask_user":
            future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
            self._user_response_futures[ctx.tool_id] = future
            await self._emit(
                {
                    "type": "ask_user",
                    "id": ctx.tool_id,
                    "questions": ctx.tool_args.get("questions", []),
                }
            )
            ctx.result = await future
            del self._user_response_futures[ctx.tool_id]
            # ask_user result rendered above; skip tool_end card
            return

        if ctx.tool_name == "todo_set" and not ctx.tool_error:
            todos = ctx.tool_args.get("todos", [])
            if isinstance(todos, list) and todos:
                await self._emit({"type": "todos", "todos": todos})

        if ctx.tool_name == "think" and not ctx.tool_error:
            thought = ctx.tool_args.get("thought", "")
            if thought:
                await self._emit({"type": "thought", "id": ctx.tool_id, "thought": thought})

        await self._emit(
            {
                "type": "tool_end",
                "tool": ctx.tool_name,
                "id": ctx.tool_id,
                "args": ctx.tool_args,
                "error": str(ctx.tool_error) if ctx.tool_error else None,
                "result": ctx.result if not ctx.tool_error else None,
            }
        )

    async def on_iteration_end(self, ctx: IterationEndContext) -> None:
        """Called at the end of each agent iteration."""

    async def on_error(self, ctx: ErrorContext) -> None:
        """Called when an error occurs."""
        await self._emit({"type": "error", "message": str(ctx.error)})
