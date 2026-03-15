"""Bridge between Session and UI.

Provides a simple message-passing interface between the agent core and UI layers.
"""

from .agent import AgentBridge
from .bus import MessageBus
from .messages import (
    Message,
    TextChunk,
    ToolCall,
    ToolResult,
    SystemMsg,
    ErrorMsg,
)

__all__ = [
    "AgentBridge",
    "MessageBus",
    "Message",
    "TextChunk",
    "ToolCall",
    "ToolResult",
    "SystemMsg",
    "ErrorMsg",
]
