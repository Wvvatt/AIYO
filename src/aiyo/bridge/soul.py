"""Soul-like wrapper for aiyo Session to work with shell UI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from aiyo.session import Session
from aiyo.tools import DEFAULT_TOOLS
from aiyo.config import settings


@dataclass
class StatusSnapshot:
    """Status snapshot for UI display."""
    context_usage: float = 0.0
    context_tokens: int = 0
    max_context_tokens: int = 128000


@dataclass 
class ModelCapability:
    """Model capability flags."""
    name: str
    supports_images: bool = False
    supports_thinking: bool = False


@dataclass
class SlashCommand:
    """Slash command definition."""
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    
    def slash_name(self) -> str:
        return f"/{self.name}"


class AiyoSoul:
    """A Soul-like wrapper around aiyo Session for UI compatibility.
    
    This provides the interface expected by the shell UI while
    delegating to the underlying aiyo Session.
    """
    
    def __init__(
        self,
        session: Session | None = None,
        model_name: str | None = None,
        work_dir: Path | None = None,
    ):
        self._session = session or Session(tools=DEFAULT_TOOLS)
        self._model_name = model_name or settings.model_name
        self._work_dir = work_dir or settings.work_dir
        self._thinking = False
        self._status = StatusSnapshot()
        self._wire_file: Path | None = None
        
    @property
    def name(self) -> str:
        return "AIYO"
    
    @property
    def model_name(self) -> str | None:
        return self._model_name
    
    @property
    def thinking(self) -> bool | None:
        return self._thinking
    
    @property
    def status(self) -> StatusSnapshot:
        # Calculate context usage from history
        history = self._session.get_history()
        # Rough token estimation
        token_count = sum(len(str(m.get("content", ""))) // 4 for m in history)
        self._status.context_tokens = token_count
        self._status.context_usage = token_count / self._status.max_context_tokens
        return self._status
    
    @property
    def model_capabilities(self) -> set[ModelCapability]:
        caps = set()
        if "vision" in self._model_name.lower() or "gpt-4" in self._model_name:
            caps.add(ModelCapability("vision", supports_images=True))
        if "o1" in self._model_name or "thinking" in self._model_name:
            caps.add(ModelCapability("thinking", supports_thinking=True))
        return caps
    
    @property
    def wire_file(self) -> Path | None:
        return self._wire_file
    
    @property
    def available_slash_commands(self) -> Sequence[SlashCommand]:
        """Return available slash commands."""
        return [
            SlashCommand("help", "Show help information", ["h", "?"]),
            SlashCommand("clear", "Clear conversation history", ["reset"]),
            SlashCommand("stats", "Show session statistics"),
            SlashCommand("history", "Show conversation history"),
            SlashCommand("save", "Save conversation history"),
            SlashCommand("compact", "Compact conversation history"),
            SlashCommand("debug", "Toggle debug mode"),
            SlashCommand("exit", "Exit the application", ["quit"]),
        ]
    
    def steer(self, message: str | list[Any]) -> None:
        """Steer the conversation (placeholder)."""
        pass
    
    async def chat(self, message: str) -> str:
        """Send a message and get response."""
        # Run in thread pool since Session.chat is synchronous
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._session.chat, message)
    
    def reset(self) -> None:
        """Reset the session."""
        self._session.reset()
    
    def get_history(self) -> list[dict[str, Any]]:
        """Get conversation history."""
        return self._session.get_history()
    
    def set_debug(self, debug: bool) -> None:
        """Set debug mode."""
        self._session.set_debug(debug)
