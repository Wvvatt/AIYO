"""Agent runner with in/out queues."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aiyo.agent.agent import Agent


@dataclass(slots=True)
class InboundMessage:
    request_id: str
    text: str
    meta: dict[str, Any] | None = None


@dataclass(slots=True)
class OutboundMessage:
    request_id: str
    text: str | None = None
    error: Exception | None = None
    meta: dict[str, Any] | None = None


class AgentRunner:
    """Run an Agent with an input/output queue per instance."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.in_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.out_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._buffer: dict[str, OutboundMessage] = {}
        self._current_task: asyncio.Task[str] | None = None

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        await self.cancel_all()
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    async def cancel_all(self) -> None:
        """Drop queued requests and cancel the in-flight request if any."""
        # Drain queued items
        try:
            while True:
                self.in_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        # Cancel in-flight task
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

    async def submit(self, text: str, meta: dict[str, Any] | None = None) -> str:
        self.start()
        request_id = uuid4().hex
        await self.in_queue.put(InboundMessage(request_id=request_id, text=text, meta=meta))
        return request_id

    async def wait_for(self, request_id: str) -> OutboundMessage:
        cached = self._buffer.pop(request_id, None)
        if cached is not None:
            return cached
        while True:
            msg = await self.out_queue.get()
            if msg.request_id == request_id:
                return msg
            self._buffer[msg.request_id] = msg

    async def _worker(self) -> None:
        while True:
            msg = await self.in_queue.get()
            try:
                self._current_task = asyncio.create_task(self.agent.chat(msg.text))
                text = await self._current_task
                await self.out_queue.put(
                    OutboundMessage(
                        request_id=msg.request_id,
                        text=text,
                        error=None,
                        meta=msg.meta,
                    )
                )
            except asyncio.CancelledError:
                await self.out_queue.put(
                    OutboundMessage(
                        request_id=msg.request_id,
                        text=None,
                        error=asyncio.CancelledError(),
                        meta=msg.meta,
                    )
                )
                raise
            except Exception as exc:
                await self.out_queue.put(
                    OutboundMessage(
                        request_id=msg.request_id,
                        text=None,
                        error=exc,
                        meta=msg.meta,
                    )
                )
            finally:
                self._current_task = None
