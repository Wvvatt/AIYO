"""Visualization for agent output in shell UI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from rich.console import Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from aiyo.bridge.wire import (
    WireUISide, StatusUpdate, ContentPart, StepBegin, StepInterrupted,
    ToolCall, ToolResult, BriefDisplayBlock, TodoDisplayBlock,
    QueueShutDown,
)
from aiyo.ui.shell.console import console


async def visualize(
    wire: WireUISide,
    *,
    initial_status: StatusUpdate,
    cancel_event: asyncio.Event | None = None,
    prompt_session: Any | None = None,
    steer: Callable[[str | list[Any]], None] | None = None,
):
    """Visualize agent events.
    
    This is a simplified version that just displays the final response.
    """
    # For now, just consume all messages without displaying live
    # The actual response is returned by the soul
    try:
        while True:
            try:
                msg = await wire.receive()
            except QueueShutDown:
                break
            
            if isinstance(msg, StepInterrupted):
                break
            
            # Process message but don't display live
            # (In a full implementation, we'd update a Live display)
    except asyncio.CancelledError:
        raise


class SimpleVisualizer:
    """Simple visualizer for agent output."""
    
    def __init__(self):
        self._current_text = ""
        self._spinner = Spinner("dots", text="Thinking...")
    
    def start(self) -> None:
        """Start visualization."""
        pass
    
    def add_text(self, text: str) -> None:
        """Add text content."""
        self._current_text += text
    
    def add_tool_call(self, name: str, args: str | None = None) -> None:
        """Add a tool call."""
        console.print(f"[dim]→ Using {name}[/dim]")
    
    def add_tool_result(self, name: str, result: Any) -> None:
        """Add a tool result."""
        pass
    
    def finish(self) -> str:
        """Finish and return the complete text."""
        return self._current_text
