"""Slash commands for the shell UI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiyo.ui.shell.console import console
from aiyo.utils.slashcmd import SlashCommand, SlashCommandRegistry

if TYPE_CHECKING:
    from aiyo.ui.shell import Shell

ShellSlashCmdFunc = Callable[["Shell", str], None | Awaitable[None]]


class Reload(Exception):
    """Exception to signal that the shell should reload."""
    pass


class SwitchToWeb(Exception):
    """Exception to signal switching to web UI."""
    pass


registry = SlashCommandRegistry[ShellSlashCmdFunc]()
shell_mode_registry = SlashCommandRegistry[ShellSlashCmdFunc]()


_SKILL_COMMAND_PREFIX = "skill:"

_KEYBOARD_SHORTCUTS = [
    ("Ctrl-X", "Toggle agent/shell mode"),
    ("Ctrl-O", "Edit in external editor ($VISUAL/$EDITOR)"),
    ("Ctrl-J / Alt-Enter", "Insert newline"),
    ("Ctrl-V", "Paste"),
    ("Ctrl-D", "Exit"),
    ("Ctrl-C", "Interrupt"),
]


@registry.command(aliases=["quit"])
@shell_mode_registry.command(aliases=["quit"])
def exit(app: "Shell", args: str):
    """Exit the application"""
    raise NotImplementedError("Should be handled by Shell")


@registry.command(aliases=["h", "?"])
@shell_mode_registry.command(aliases=["h", "?"])
def help(app: "Shell", args: str):
    """Show help information"""
    from rich.console import Group, RenderableType
    from rich.text import Text
    
    from aiyo.utils.slashcmd import SlashCommand
    
    def section(title: str, items: list[tuple[str, str]], color: str):
        lines: list[RenderableType] = [Text.from_markup(f"[bold]{title}:[/bold]")]
        for name, desc in items:
            lines.append(Text.from_markup(f"  [{color}]{name}[/{color}]: [grey50]{desc}[/grey50]"))
        return Group(*lines)
    
    renderables: list[RenderableType] = []
    renderables.append(
        Text("AIYO - AI automation agent for Amlogic R&D")
    )
    
    commands: list[SlashCommand[Any]] = []
    for cmd in app.available_slash_commands.values():
        if not cmd.name.startswith(_SKILL_COMMAND_PREFIX):
            commands.append(cmd)
    
    renderables.append(section("Keyboard shortcuts", _KEYBOARD_SHORTCUTS, "yellow"))
    renderables.append(
        section(
            "Slash commands",
            [(c.slash_name(), c.description) for c in sorted(commands, key=lambda c: c.name)],
            "blue",
        )
    )
    
    console.print(Group(*renderables))


@registry.command
@shell_mode_registry.command
def version(app: "Shell", args: str):
    """Show version information"""
    console.print("AIYO version 0.1.0")


@registry.command
async def clear(app: "Shell", args: str):
    """Clear the conversation history"""
    app.soul.reset()
    console.print("[green]Conversation history cleared.[/green]")
    raise Reload()


@registry.command
async def stats(app: "Shell", args: str):
    """Show session statistics"""
    from aiyo.bridge import StatusSnapshot
    
    status = app.soul.status
    console.print(f"Context usage: {status.context_usage:.1%}")
    console.print(f"Context tokens: {status.context_tokens}")
    console.print(f"Max tokens: {status.max_context_tokens}")


@registry.command
async def history(app: "Shell", args: str):
    """Show conversation history"""
    history = app.soul.get_history()
    for i, msg in enumerate(history):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = str(content)
        elif isinstance(content, str):
            content = content[:100] + "..." if len(content) > 100 else content
        console.print(f"{i+1}. [{role}] {content}")


@registry.command(aliases=["reset"])
async def new(app: "Shell", args: str):
    """Start a new session"""
    app.soul.reset()
    console.print("[green]New session started.[/green]")
    raise Reload()


@registry.command
async def debug(app: "Shell", args: str):
    """Toggle debug mode"""
    # Get current state from somewhere or toggle
    # For now, just toggle
    current_debug = False  # We don't track this currently
    new_debug = not current_debug
    app.soul.set_debug(new_debug)
    console.print(f"[green]Debug mode {'enabled' if new_debug else 'disabled'}.[/green]")
