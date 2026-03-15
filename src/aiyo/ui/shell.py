"""Interactive shell UI — Claude Code style."""

from __future__ import annotations

import asyncio
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.status import Status

from aiyo.bridge import AgentBridge
from aiyo.bridge.messages import (
    ErrorMsg,
    TextChunk,
    ToolCall,
    TurnEnd,
)

console = Console()


class AiyoCompleter(Completer):
    """Completer for slash commands and file paths."""

    COMMANDS = {
        "/help": "Show help",
        "/clear": "Clear screen",
        "/reset": "Reset conversation",
        "/stats": "Show statistics",
        "/compact": "Compress history",
        "/exit": "Exit",
    }

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # Slash commands: only when `/` is the first char and no spaces yet
        if text.startswith("/") and " " not in text:
            for cmd, desc in self.COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text), display_meta=desc)
            return

        # Path completion after @
        yield from self._at_path_completions(text)

    def _at_path_completions(self, text: str):
        """Complete file/directory paths after '@'."""
        # Find the last @ token
        at_idx = text.rfind("@")
        if at_idx == -1:
            return

        path_part = text[at_idx + 1 :]
        # Stop if there's a space after the path (user moved on)
        if " " in path_part:
            return

        expanded = os.path.expanduser(path_part) if path_part else "."
        search_dir = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded)

        try:
            entries = os.listdir(search_dir)
        except OSError:
            return

        for entry in sorted(entries):
            if entry.startswith(".") and not prefix.startswith("."):
                continue
            if not entry.lower().startswith(prefix.lower()):
                continue

            full = os.path.join(search_dir, entry)
            is_dir = os.path.isdir(full)

            # Build completion: @dir_part/entry
            dir_part = os.path.dirname(path_part)
            if dir_part:
                completion = "@" + os.path.join(dir_part, entry)
            else:
                completion = "@" + entry

            if is_dir:
                completion += "/"

            # Replace from the @ onward
            replace_len = len(path_part) + 1  # +1 for @

            yield Completion(
                completion,
                start_position=-replace_len,
                display=entry + ("/" if is_dir else ""),
                display_meta="dir" if is_dir else "",
            )


def _format_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 0 -> '0'."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class ShellUI:
    """Interactive shell UI in Claude Code style."""

    def __init__(self, agent: AgentBridge | None = None, model_name: str = "") -> None:
        self.agent = agent or AgentBridge()
        self._model_name = model_name or self.agent.model_name
        self._running = False
        self._status_text = ""

        # Setup prompt session
        kb = self._setup_keybindings()
        self._session = PromptSession(
            message="> ",
            bottom_toolbar=self._toolbar,
            completer=AiyoCompleter(),
            complete_while_typing=True,
            key_bindings=kb,
            multiline=False,
            enable_history_search=True,
        )

    def _setup_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-d")
        def exit_app(event):
            if not event.app.current_buffer.text:
                event.app.exit()

        @kb.add("escape", eager=True)
        def cancel_op(event):
            asyncio.create_task(self.agent.cancel())

        @kb.add("/", eager=True)
        def slash_complete(event):
            buf = event.app.current_buffer
            buf.insert_text("/")
            if buf.text.startswith("/") and " " not in buf.text:
                buf.start_completion()

        @kb.add("@", eager=True)
        def at_complete(event):
            buf = event.app.current_buffer
            buf.insert_text("@")
            buf.start_completion()

        return kb

    def _toolbar(self) -> HTML:
        """Bottom status bar."""
        stats = self.agent.session_stats
        tokens_in = _format_tokens(stats.total_input_tokens)
        tokens_out = _format_tokens(stats.total_output_tokens)
        duration = self.agent.last_turn_duration

        parts = [f"model: {self._model_name}"]
        parts.append(f"tokens: {tokens_in}/{tokens_out}")
        if duration > 0:
            parts.append(f"last: {duration:.1f}s")
        if self._status_text:
            parts.append(self._status_text)

        return HTML(f" <style bg='#333333' fg='#cccccc'>{' | '.join(parts)}</style>")

    async def run(self) -> None:
        """Main interactive loop."""
        self._running = True
        self._show_welcome()

        while self._running:
            try:
                with patch_stdout():
                    text = await self._session.prompt_async()

                if not text.strip():
                    continue

                await self._handle_input(text.strip())

            except (EOFError, KeyboardInterrupt):
                break

        console.print("\n[dim]Bye![/dim]")

    async def _handle_input(self, text: str) -> None:
        """Process user input."""
        if text.startswith("/"):
            await self._handle_slash(text)
            return

        await self._chat(text)

    async def _handle_slash(self, cmd: str) -> None:
        """Handle slash commands."""
        parts = cmd.split(maxsplit=1)
        name = parts[0].lower()

        match name:
            case "/help":
                self._show_help()
            case "/clear":
                console.clear()
            case "/stats":
                self._show_stats()
            case "/reset":
                self.agent.reset()
                console.print("[dim]Session reset.[/dim]")
            case "/compact":
                console.print("[dim]Compacting history...[/dim]")
                self.agent.session.compact()
                console.print("[dim]Done.[/dim]")
            case "/exit":
                self._running = False
            case _:
                console.print(f"[red]Unknown command: {cmd}[/red]")

    async def _chat(self, message: str) -> None:
        """Chat with agent, stream and display response."""
        await self.agent.chat(message)

        response_text = ""
        with Status("[dim]Thinking...[/dim]", console=console, spinner="dots"):
            async for msg in self.agent.bus.iter():
                if isinstance(msg, TextChunk):
                    response_text += msg.content
                elif isinstance(msg, ToolCall):
                    self._show_tool(msg)
                elif isinstance(msg, ErrorMsg):
                    console.print(f"\n[red]Error: {msg.error}[/red]")
                    break
                elif isinstance(msg, TurnEnd):
                    break

        if response_text:
            console.print()
            console.print(Markdown(response_text))
        console.print()

    def _show_tool(self, msg: ToolCall) -> None:
        """Display tool call in Claude Code style: indented, gray."""
        name = self._format_tool_name(msg.name)
        args_str = self._format_tool_args(msg)
        console.print(f"  [dim]{name}[/dim] [dim italic]{args_str}[/dim italic]")

    def _format_tool_name(self, name: str) -> str:
        """Convert snake_case to CamelCase."""
        return "".join(part.capitalize() for part in name.split("_"))

    def _format_tool_args(self, msg: ToolCall) -> str:
        """Extract the most relevant arg for display."""
        match msg.name:
            case "read_file":
                return msg.args.get("path", "")
            case "write_file":
                path = msg.args.get("path", "")
                content = msg.args.get("content", "")
                lines = content.count("\n") + 1 if content else 0
                return f"{path} ({lines} lines)" if path else ""
            case "str_replace_file":
                return msg.args.get("path", "")
            case "list_directory":
                return msg.args.get("relative_path", ".")
            case "glob_files":
                return msg.args.get("pattern", "")
            case "grep_files":
                return msg.args.get("pattern", "")
            case "run_shell_command":
                cmd = msg.args.get("command", "")
                return cmd[:80] + ("..." if len(cmd) > 80 else "")
            case "think":
                thought = msg.args.get("thought", "")
                return thought[:60] + ("..." if len(thought) > 60 else "")
            case "fetch_url":
                return msg.args.get("url", "")
            case "todo":
                action = msg.args.get("action", "list")
                task = msg.args.get("task", "")
                return f"{action} {task}".strip()
            case _:
                # Generic: show first string arg
                for v in msg.args.values():
                    if isinstance(v, str) and v:
                        return v[:60] + ("..." if len(v) > 60 else "")
                return ""

    def _show_welcome(self) -> None:
        """One-line welcome."""
        console.print(f"[bold]AIYO[/bold] v0.1.0 [dim]• {self._model_name}[/dim]\n")

    def _show_help(self) -> None:
        """Show help info."""
        console.print("[bold]Commands:[/bold]")
        console.print("  [dim]/help[/dim]     Show this help")
        console.print("  [dim]/clear[/dim]    Clear screen")
        console.print("  [dim]/reset[/dim]    Reset conversation")
        console.print("  [dim]/stats[/dim]    Show statistics")
        console.print("  [dim]/compact[/dim]  Compress history")
        console.print("  [dim]/exit[/dim]     Exit")
        console.print()
        console.print("[bold]Keys:[/bold]")
        console.print("  [dim]Enter[/dim]     Submit input")
        console.print("  [dim]Esc[/dim]      Cancel operation")
        console.print("  [dim]Ctrl-D[/dim]   Exit")
        console.print()

    def _show_stats(self) -> None:
        """Show session statistics."""
        stats = self.agent.session_stats
        console.print(stats.print_summary())
