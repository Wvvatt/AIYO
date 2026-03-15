"""Bridge between Session and MessageBus."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from aiyo.session import Session

from .bus import MessageBus
from .messages import (
    ErrorMsg,
    Message,
    SystemMsg,
    TextChunk,
    ToolCall,
    ToolResult,
    TurnEnd,
    TurnStart,
)


class AgentBridge:
    """Wraps a Session and exposes it via MessageBus.

    This bridges the synchronous Session API with async message-based UI.
    """

    def __init__(self, session: Session | None = None) -> None:
        self.session = session or Session()
        self.bus = MessageBus()
        self._task: asyncio.Task[None] | None = None
        self._cancelled = False
        self._last_turn_duration: float = 0.0

    @property
    def model_name(self) -> str:
        """Get the model name from the session."""
        return self.session._model

    @property
    def last_turn_duration(self) -> float:
        """Duration of the last turn in seconds."""
        return self._last_turn_duration

    async def chat(self, message: str) -> None:
        """Start a chat turn in the background."""
        if self._task and not self._task.done():
            await self.cancel()

        self._cancelled = False
        self._task = asyncio.create_task(self._run_chat(message))

    async def _run_chat(self, message: str) -> None:
        """Run chat and stream messages to bus."""
        await self.bus.send(TurnStart())

        t0 = time.monotonic()
        try:
            # Run sync session.chat in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.session.chat, message)

            # Stream response as chunks
            await self.bus.send(TextChunk(response))

        except Exception as e:
            await self.bus.send(ErrorMsg(str(e)))

        self._last_turn_duration = time.monotonic() - t0
        await self.bus.send(TurnEnd())

    async def cancel(self) -> None:
        """Cancel current operation."""
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def reset(self) -> None:
        """Reset session."""
        self.session.reset()

    def get_history(self) -> list[dict[str, Any]]:
        """Get conversation history."""
        return self.session.get_history()

    @property
    def stats(self) -> dict[str, Any]:
        """Get session stats."""
        return self.session.get_history_summary()

    @property
    def session_stats(self) -> Any:
        """Get the SessionStats object for detailed stats."""
        return self.session._stats
