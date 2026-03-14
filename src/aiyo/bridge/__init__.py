"""Bridge module to adapt aiyo Session to kimi-cli style interfaces."""

from .soul import AiyoSoul, StatusSnapshot, ModelCapability
from .wire import (
    SimpleWire, WireUISide, WireMessage, QueueShutDown,
    ContentPart, TextPart, ThinkPart,
    StepBegin, StepInterrupted, TurnBegin, TurnEnd,
    ToolCall, ToolCallFunction, ToolCallPart, ToolResult, ToolReturnValue,
    StatusUpdate,
    BriefDisplayBlock, TodoDisplayBlock, TodoItem, DiffDisplayBlock, ShellDisplayBlock,
    ApprovalRequest, QuestionRequest, Question, QuestionOption,
    MCPLoadingBegin, MCPLoadingEnd, CompactionBegin, CompactionEnd, SubagentEvent,
)

__all__ = [
    "AiyoSoul", "StatusSnapshot", "ModelCapability",
    "SimpleWire", "WireUISide", "WireMessage", "QueueShutDown",
    "ContentPart", "TextPart", "ThinkPart",
    "StepBegin", "StepInterrupted", "TurnBegin", "TurnEnd",
    "ToolCall", "ToolCallFunction", "ToolCallPart", "ToolResult", "ToolReturnValue",
    "StatusUpdate",
    "BriefDisplayBlock", "TodoDisplayBlock", "TodoItem", "DiffDisplayBlock", "ShellDisplayBlock",
    "ApprovalRequest", "QuestionRequest", "Question", "QuestionOption",
    "MCPLoadingBegin", "MCPLoadingEnd", "CompactionBegin", "CompactionEnd", "SubagentEvent",
]
