"""Simple async message bus for agent-ui communication."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from .messages import Message

T = TypeVar("T", bound=Message)


class MessageBus:
    """Async message bus with typed filtering."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._closed = False

    async def send(self, msg: Message) -> None:
        """Send a message to the bus."""
        if not self._closed:
            await self._queue.put(msg)

    async def recv(self) -> Message:
        """Receive the next message."""
        if self._closed:
            raise RuntimeError("Bus is closed")
        return await self._queue.get()

    def recv_nowait(self) -> Message | None:
        """Try to receive without blocking."""
        if self._closed:
            return None
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def iter(self, msg_type: type[T] | None = None) -> AsyncIterator[T]:
        """Iterate over messages, optionally filtered by type."""
        while True:
            msg = await self.recv()
            if msg_type is None or isinstance(msg, msg_type):
                yield msg  # type: ignore

    def close(self) -> None:
        """Close the bus."""
        self._closed = True

    def __aiter__(self) -> AsyncIterator[Message]:
        """Async iterate over all messages."""
        return self.iter()
