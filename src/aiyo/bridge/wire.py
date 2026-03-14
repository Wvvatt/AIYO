"""Wire protocol for communication between agent and UI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ContentPart:
    """Content part in a message."""
    type: Literal["text", "image", "thinking"]
    content: str = ""
    
    def merge_in_place(self, other: "ContentPart") -> bool:
        """Try to merge another content part into this one."""
        if self.type == other.type and self.type == "text":
            self.content += other.content
            return True
        return False


@dataclass
class TextPart(ContentPart):
    """Text content part."""
    def __init__(self, text: str = ""):
        super().__init__(type="text", content=text)


@dataclass
class ThinkPart(ContentPart):
    """Thinking content part."""
    def __init__(self, text: str = ""):
        super().__init__(type="thinking", content=text)


@dataclass
class StepBegin:
    """Signal the beginning of a step."""
    pass


@dataclass
class StepInterrupted:
    """Signal that the step was interrupted."""
    pass


@dataclass
class TurnBegin:
    """Signal the beginning of a turn."""
    pass


@dataclass
class TurnEnd:
    """Signal the end of a turn."""
    pass


@dataclass
class ToolCall:
    """Tool call message."""
    id: str
    function: "ToolCallFunction"


@dataclass
class ToolCallFunction:
    """Function details in a tool call."""
    name: str
    arguments: str | None = None


@dataclass
class ToolCallPart:
    """Partial tool call (streaming)."""
    tool_call_id: str
    arguments_part: str


@dataclass
class ToolResult:
    """Tool execution result."""
    tool_call_id: str
    return_value: "ToolReturnValue"


@dataclass
class ToolReturnValue:
    """Tool return value."""
    is_error: bool
    display: list[Any] = field(default_factory=list)


@dataclass
class StatusUpdate:
    """Status update message."""
    context_usage: float | None = None
    context_tokens: int | None = None
    max_context_tokens: int | None = None


@dataclass  
class BriefDisplayBlock:
    """Brief display block."""
    text: str


@dataclass
class TodoItem:
    """Todo item."""
    title: str
    status: str


@dataclass
class TodoDisplayBlock:
    """Todo display block."""
    items: list[TodoItem] = field(default_factory=list)


@dataclass
class DiffDisplayBlock:
    """Diff display block."""
    path: str
    old_text: str
    new_text: str


@dataclass
class ShellDisplayBlock:
    """Shell command display block."""
    command: str
    language: str = "bash"


@dataclass
class ApprovalRequest:
    """Approval request from agent."""
    sender: str
    action: str
    description: str = ""
    display: list[Any] = field(default_factory=list)
    
    def resolve(self, response: Any) -> None:
        """Resolve the approval request."""
        pass


@dataclass
class QuestionRequest:
    """Question request from agent."""
    questions: list["Question"] = field(default_factory=list)
    
    def resolve(self, answers: dict[str, str]) -> None:
        """Resolve with answers."""
        pass


@dataclass
class Question:
    """A question in a question request."""
    question: str
    header: str | None = None
    body: str | None = None
    options: list["QuestionOption"] = field(default_factory=list)
    multi_select: bool = False
    other_label: str | None = None
    other_description: str | None = None


@dataclass
class QuestionOption:
    """An option in a question."""
    label: str
    description: str | None = None


@dataclass
class MCPLoadingBegin:
    """MCP loading begin signal."""
    pass


@dataclass
class MCPLoadingEnd:
    """MCP loading end signal."""
    pass


@dataclass
class CompactionBegin:
    """Compaction begin signal."""
    pass


@dataclass
class CompactionEnd:
    """Compaction end signal."""
    pass


@dataclass
class SubagentEvent:
    """Subagent event."""
    event_type: str
    data: Any = None


WireMessage = (
    ContentPart | StepBegin | StepInterrupted | TurnBegin | TurnEnd |
    ToolCall | ToolCallPart | ToolResult | StatusUpdate |
    BriefDisplayBlock | TodoDisplayBlock | DiffDisplayBlock | ShellDisplayBlock |
    ApprovalRequest | QuestionRequest | MCPLoadingBegin | MCPLoadingEnd |
    CompactionBegin | CompactionEnd | SubagentEvent
)


class QueueShutDown(Exception):
    """Exception raised when queue is shut down."""
    pass


class SimpleWire:
    """Simple wire implementation for UI-agent communication."""
    
    def __init__(self):
        self._queue: asyncio.Queue[WireMessage] = asyncio.Queue()
        self._closed = False
    
    def send(self, message: WireMessage) -> None:
        """Send a message through the wire."""
        if not self._closed:
            self._queue.put_nowait(message)
    
    async def receive(self) -> WireMessage:
        """Receive a message from the wire."""
        if self._closed:
            raise QueueShutDown()
        return await self._queue.get()
    
    def close(self) -> None:
        """Close the wire."""
        self._closed = True
    
    def ui_side(self, merge: bool = False) -> "WireUISide":
        """Get the UI side of the wire."""
        return WireUISide(self)


class WireUISide:
    """UI side interface for the wire."""
    
    def __init__(self, wire: SimpleWire):
        self._wire = wire
    
    async def receive(self) -> WireMessage:
        """Receive a message."""
        return await self._wire.receive()
    
    def close(self) -> None:
        """Close the wire."""
        self._wire.close()
