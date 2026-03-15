"""Message types for agent-ui communication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    """Base message type."""
    pass


@dataclass
class TextChunk(Message):
    """Streaming text chunk from agent."""
    content: str


@dataclass
class ToolCall(Message):
    """Tool invocation notification."""
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult(Message):
    """Tool execution result."""
    name: str
    result: Any
    success: bool = True


@dataclass
class SystemMsg(Message):
    """System status message."""
    content: str
    level: Literal["info", "warning", "error"] = "info"


@dataclass
class ErrorMsg(Message):
    """Error message."""
    error: str
    details: str = ""


@dataclass
class TurnStart(Message):
    """Mark the start of a new turn."""
    pass


@dataclass
class TurnEnd(Message):
    """Mark the end of a turn."""
    pass


