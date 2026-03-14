"""Slash command parsing and registry."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


@dataclass
class SlashCommandCall:
    """A parsed slash command call."""
    name: str
    args: str
    raw_input: str


def parse_slash_command_call(text: str) -> SlashCommandCall | None:
    """Parse a slash command call from text.
    
    Args:
        text: The text to parse.
        
    Returns:
        A SlashCommandCall if the text is a slash command, None otherwise.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None
    
    # Remove the leading slash
    content = text[1:]
    
    # Split into name and args
    match = re.match(r'(\S+)(?:\s+(.*))?$', content, re.DOTALL)
    if not match:
        return None
    
    name = match.group(1)
    args = match.group(2) or ""
    
    return SlashCommandCall(name=name, args=args, raw_input=text)


T = TypeVar("T")


@dataclass
class SlashCommand(Generic[T]):
    """A slash command definition."""
    name: str
    func: Callable[[Any, str], T]
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    
    def slash_name(self) -> str:
        return f"/{self.name}"


class SlashCommandRegistry(Generic[T]):
    """Registry for slash commands."""
    
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand[T]] = {}
    
    def command(
        self,
        name: str | None = None,
        aliases: list[str] | None = None,
    ) -> Callable[[Callable[[Any, str], T]], SlashCommand[T]]:
        """Decorator to register a slash command."""
        def decorator(func: Callable[[Any, str], T]) -> SlashCommand[T]:
            # Handle case where func is already a SlashCommand (from stacking decorators)
            if isinstance(func, SlashCommand):
                actual_func = func.func
                actual_name = name or func.name
            else:
                actual_func = func
                actual_name = name or func.__name__
            
            cmd = SlashCommand(
                name=actual_name,
                func=actual_func,
                description=actual_func.__doc__ or "",
                aliases=aliases or [],
            )
            self._commands[actual_name] = cmd
            for alias in (aliases or []):
                self._commands[alias] = cmd
            return cmd
        return decorator
    
    def find_command(self, name: str) -> SlashCommand[T] | None:
        """Find a command by name."""
        return self._commands.get(name)
    
    def list_commands(self) -> list[SlashCommand[T]]:
        """List all unique commands (not aliases)."""
        seen = set()
        result = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                result.append(cmd)
        return sorted(result, key=lambda c: c.name)
