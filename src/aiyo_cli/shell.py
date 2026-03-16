"""Interactive shell UI — Claude Code style."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.status import Status
from rich.theme import Theme

from aiyo import DEFAULT_TOOLS, Session

console = Console(theme=Theme({"markdown.code": "bold cyan"}))


class AiyoCompleter(Completer):
    """Completer for slash commands and file paths."""

    COMMANDS = {
        "/help": "Show help",
        "/clear": "Clear screen",
        "/reset": "Reset conversation",
        "/stats": "Show statistics",
        "/summary": "Show history token usage",
        "/compact": "Compress history",
        "/save": "Save history to .history/",
        "/debug": "Enable debug logging",
        "/nodebug": "Disable debug logging",
        "/exit": "Exit",
    }

    @staticmethod
    def _fuzzy_match(pattern: str, text: str) -> bool:
        """Return True if all chars of pattern appear in text in order."""
        it = iter(text)
        return all(c in it for c in pattern)

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # Slash commands: only when `/` is the first char and no spaces yet
        if text.startswith("/") and " " not in text:
            for cmd, desc in self.COMMANDS.items():
                if self._fuzzy_match(text, cmd):
                    yield Completion(cmd, start_position=-len(text), display_meta=desc)
            return

        # Path completion after @
        yield from self._at_path_completions(text)

    # Directories to skip during recursive file search
    _SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"})

    def _at_path_completions(self, text: str):
        """Complete file/directory paths after '@'.

        - With a '/': standard directory listing (e.g. @src/aiyo/)
        - Without '/': recursive fuzzy search by filename across cwd
        """
        at_idx = text.rfind("@")
        if at_idx == -1:
            return

        path_part = text[at_idx + 1 :]
        if " " in path_part:
            return

        if "/" in path_part:
            yield from self._dir_completions(path_part)
        else:
            yield from self._fuzzy_file_completions(path_part)

    def _dir_completions(self, path_part: str):
        """List entries in the specified directory (original behaviour)."""
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
            dir_part = os.path.dirname(path_part)
            completion = "@" + (os.path.join(dir_part, entry) if dir_part else entry)
            if is_dir:
                completion += "/"

            yield Completion(
                completion,
                start_position=-(len(path_part) + 1),
                display=entry + ("/" if is_dir else ""),
                display_meta="dir" if is_dir else "",
            )

    def _fuzzy_file_completions(self, query: str):
        """Recursively search cwd for files whose name fuzzy-matches query."""
        from pathlib import Path

        cwd = Path(".")
        pattern = query.lower()
        matches: list[Path] = []

        for path in cwd.rglob("*"):
            if any(part in self._SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if pattern and not self._fuzzy_match(pattern, path.name.lower()):
                continue
            matches.append(path)
            if len(matches) >= 50:  # cap results
                break

        for path in sorted(matches, key=lambda p: p.name):
            rel = str(path)
            yield Completion(
                "@" + rel,
                start_position=-(len(query) + 1),
                display=path.name,
                display_meta=str(path.parent),
            )


def _format_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 0 -> '0'."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class ShellUI:
    """Interactive shell UI in Claude Code style."""

    def __init__(self, session: Session | None = None) -> None:
        self._agent_session = session or Session(DEFAULT_TOOLS)
        self._model_name = self._agent_session.model_name
        self._running = False
        self._last_turn_duration: float = 0.0

        # Setup prompt session
        kb = self._setup_keybindings()
        self._prompt_session = PromptSession(
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
            self._agent_session.cancel()

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
        stats = self._agent_session.stats
        tokens_in = _format_tokens(stats.total_input_tokens)
        tokens_out = _format_tokens(stats.total_output_tokens)
        duration = self._last_turn_duration

        parts = [f"model: {self._model_name}"]
        parts.append(f"tokens: {tokens_in}/{tokens_out}")
        if duration > 0:
            parts.append(f"last: {duration:.1f}s")

        return HTML(f" <style bg='#333333' fg='#cccccc'>{' | '.join(parts)}</style>")

    async def run(self) -> None:
        """Main interactive loop."""
        self._running = True
        self._show_welcome()

        while self._running:
            try:
                with patch_stdout():
                    text = await self._prompt_session.prompt_async()

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
            case "/help" | "/h":
                self._show_help()
            case "/clear":
                console.clear()
            case "/stats":
                self._show_stats()
            case "/summary":
                self._show_summary()
            case "/reset":
                self._agent_session.reset()
                console.print("[dim]Session reset.[/dim]")
            case "/compact":
                console.print("[dim]Compacting history...[/dim]")
                result = self._agent_session.compact()
                console.print(f"[dim]{result}[/dim]")
            case "/save":
                self._save_history()
            case "/debug":
                self._agent_session.set_debug(True)
                console.print("[dim]Debug mode enabled.[/dim]")
            case "/nodebug":
                self._agent_session.set_debug(False)
                console.print("[dim]Debug mode disabled.[/dim]")
            case "/exit":
                self._running = False
            case _:
                console.print(f"[red]Unknown command: {cmd}[/red]")

    async def _chat(self, message: str) -> None:
        """Chat with agent and display response."""
        t0 = time.monotonic()

        with Status("[dim]Thinking...[/dim]", console=console, spinner="dots"):
            response = await self._agent_session.chat(message)

        self._last_turn_duration = time.monotonic() - t0

        if response:
            console.print()
            console.print(Markdown(response))
        console.print()

    def _show_welcome(self) -> None:
        """One-line welcome."""
        console.print(f"[bold]AIYO[/bold] v0.1.0 [dim]• {self._model_name}[/dim]\n")

    def _show_help(self) -> None:
        """Show help info."""
        console.print("[bold]Commands:[/bold]")
        console.print("  [dim]/help, /h[/dim]       Show this help")
        console.print("  [dim]/clear[/dim]           Clear screen")
        console.print("  [dim]/reset[/dim]           Reset conversation")
        console.print("  [dim]/stats[/dim]           Show statistics")
        console.print("  [dim]/summary[/dim]         Show history token usage")
        console.print("  [dim]/compact[/dim]         Compress history")
        console.print("  [dim]/save[/dim]            Save history to .history/")
        console.print("  [dim]/debug[/dim]           Enable debug logging")
        console.print("  [dim]/nodebug[/dim]         Disable debug logging")
        console.print("  [dim]/exit[/dim]             Exit")
        console.print()
        console.print("[bold]Keys:[/bold]")
        console.print("  [dim]Enter[/dim]     Submit input")
        console.print("  [dim]Esc[/dim]       Cancel operation")
        console.print("  [dim]Ctrl-D[/dim]    Exit")
        console.print()

    def _show_stats(self) -> None:
        """Show session statistics."""
        stats = self._agent_session.stats
        console.print(stats.print_summary())

    def _show_summary(self) -> None:
        """Show history token usage summary."""
        summary = self._agent_session.get_history_summary()
        console.print(f"Messages: {summary.get('message_count', 0)}")
        console.print(
            f"Tokens:   {summary.get('token_count', 0)} / {summary.get('token_limit', 0)}"
        )
        console.print(f"Usage:    {summary.get('token_usage_percent', 0):.1f}%")
        if "role_counts" in summary:
            console.print(f"Roles:    {summary['role_counts']}")

    def _save_history(self) -> None:
        """Save conversation history to .history/."""
        history_dir = Path(".history")
        history_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = history_dir / f"history_{timestamp}.jsonl"
        history = self._agent_session.get_history()
        with open(save_path, "w", encoding="utf-8") as f:
            for msg in history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        console.print(f"[dim]History saved to {save_path} ({len(history)} messages)[/dim]")
