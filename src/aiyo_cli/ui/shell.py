"""Interactive shell UI — Claude Code style."""

from __future__ import annotations

import asyncio
import signal
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.markdown import Markdown
from rich.status import Status

from aiyo import DEFAULT_TOOLS, Agent
from aiyo.config import settings

try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []

from .completer import AiyoCompleter
from .middleware import DiffMiddleware, PlanModeMiddleware, ToolDisplayMiddleware
from .theme import CODE_THEME, SPINNER_TEXT, console, format_tokens, get_palette


class ShellUI:
    """Interactive shell UI in Claude Code style."""

    _PASTE_THRESHOLD = 5  # lines; below this paste inline, above show placeholder

    def __init__(self, agent: Agent | None = None) -> None:
        self._paste_store: dict[str, str] = {}
        self._plan_middleware = PlanModeMiddleware()
        self._agent_session = agent or Agent(
            tools=DEFAULT_TOOLS + EXT_TOOLS,
            extra_middleware=[
                ToolDisplayMiddleware(),
                DiffMiddleware(),
                self._plan_middleware,
            ],
        )
        self._model_name = self._agent_session.model_name
        self._running = False
        self._last_turn_duration: float = 0.0
        self._palette = get_palette()

        # Setup prompt session
        kb = self._setup_keybindings()
        style = Style.from_dict(
            {
                "bottom-toolbar": "noreverse",
            }
        )
        self._prompt_session = PromptSession(
            message="> ",
            bottom_toolbar=self._toolbar,
            completer=AiyoCompleter(),
            complete_while_typing=True,
            key_bindings=kb,
            multiline=False,
            enable_history_search=True,
            style=style,
        )

    def _setup_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-d")
        def exit_or_clear(event):
            buf = event.app.current_buffer
            if not buf.text:
                event.app.exit()
            else:
                buf.text = ""

        @kb.add("/")
        def slash_complete(event):
            buf = event.app.current_buffer
            buf.insert_text("/")
            if buf.text.startswith("/") and " " not in buf.text:
                buf.start_completion()

        @kb.add("@")
        def at_complete(event):
            buf = event.app.current_buffer
            buf.insert_text("@")
            buf.start_completion()

        @kb.add("s-tab")  # Shift-Tab to toggle plan mode
        def toggle_plan_mode(event):
            if self._plan_middleware.toggle():
                (settings.work_dir / ".plan").mkdir(exist_ok=True)

        @kb.add(Keys.BracketedPaste)
        def paste(event):
            content = event.data
            lines = content.splitlines()
            if len(lines) >= self._PASTE_THRESHOLD:
                placeholder = f"[pasted: {len(lines)} lines]"
                self._paste_store[placeholder] = content
                event.app.current_buffer.insert_text(placeholder)
            else:
                event.app.current_buffer.insert_text(content)

        return kb

    def _toolbar(self) -> HTML:
        """Bottom status bar with HTML styling."""
        stats = self._agent_session.stats
        tokens_in = format_tokens(stats.total_input_tokens)
        tokens_out = format_tokens(stats.total_output_tokens)
        duration = self._last_turn_duration

        parts = []
        mode = "[PLAN MODE]" if self._plan_middleware.is_active else "[NORMAL MODE]"
        parts.append(f"<span fg='{self._palette['accent']}'>{mode}</span> (⇧+Tab)")
        parts.append(f"model: {self._model_name}")
        parts.append(f"tokens: {tokens_in}/{tokens_out}")
        if duration > 0:
            parts.append(f"last: {duration:.1f}s")
        parts.append("/help")

        separator = f"<span fg='{self._palette['muted']}'>{'─' * 60}</span>"
        content = " | ".join(parts)
        return HTML(f"{separator}\n{content}")

    async def run(self) -> None:
        """Main interactive loop."""
        self._running = True
        self._show_welcome()

        while self._running:
            try:
                with patch_stdout():
                    text = await self._prompt_session.prompt_async()

                if text is None:
                    break
                if not text.strip():
                    continue

                await self._handle_input(text.strip())

            except (EOFError, KeyboardInterrupt):
                break

        self._show_stats()
        console.print("[muted]Bye![/muted]")

    async def _handle_input(self, text: str) -> None:
        """Process user input."""
        if text.startswith("/"):
            await self._handle_slash(text)
            return

        for placeholder, content in self._paste_store.items():
            text = text.replace(placeholder, content)
        self._paste_store.clear()

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
                console.print("[muted]Session reset.[/muted]")
            case "/compact":
                console.print("[muted]Compacting history...[/muted]")
                result = await self._agent_session.compact()
                if result:
                    console.print(f"[muted]{result}[/muted]")
            case "/save":
                self._save_history()
            case "/exit":
                self._running = False
            case _:
                console.print(f"[error]Unknown command: {cmd}[/error]")

    async def _chat(self, message: str) -> None:
        """Chat with agent and display response."""
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()

        def _on_sigint():
            self._agent_session.cancel()
            if task:
                task.cancel()

        loop.add_signal_handler(signal.SIGINT, _on_sigint)
        try:
            with Status(SPINNER_TEXT, console=console, spinner="dots"):
                response = await self._agent_session.chat(message)
        except asyncio.CancelledError:
            console.print("\n[muted]Cancelled.[/muted]")
            return
        finally:
            loop.remove_signal_handler(signal.SIGINT)

        self._last_turn_duration = time.monotonic() - t0

        if response:
            console.print()
            console.print(Markdown(response, code_theme=CODE_THEME))
        console.print()

    def _show_welcome(self) -> None:
        """Banner + model info."""
        banner = (
            "[tool]"
            "  ██████╗ ██╗██╗   ██╗ ██████╗\n"
            " ██╔══██╗██║╚██╗ ██╔╝██╔═══██╗\n"
            " ███████║██║ ╚████╔╝ ██║   ██║\n"
            " ██╔══██║██║  ╚██╔╝  ██║   ██║\n"
            " ██║  ██║██║   ██║   ╚██████╔╝\n"
            " ╚═╝  ╚═╝╚═╝   ╚═╝    ╚═════╝ \n"
            " Agent In Your Orbit"
            "[/tool]\n"
        )
        console.print(banner)

    def _show_help(self) -> None:
        """Show help info."""
        console.print("[heading]Commands:[/heading]")
        console.print("  [muted]/help, /h[/muted]       Show this help")
        console.print("  [muted]/clear[/muted]           Clear screen")
        console.print("  [muted]/reset[/muted]           Reset conversation")
        console.print("  [muted]/stats[/muted]           Show statistics")
        console.print("  [muted]/summary[/muted]         Show history token usage")
        console.print("  [muted]/compact[/muted]         Compress history")
        console.print("  [muted]/save[/muted]            Save history to .history/")
        console.print("  [muted]/exit[/muted]             Exit")
        console.print()
        console.print("[heading]Keys:[/heading]")
        console.print("  [muted]Enter[/muted]     Submit input")
        console.print("  [muted]Ctrl-C[/muted]    Cancel running task (or clear input)")
        console.print("  [muted]Ctrl-D[/muted]    Exit")
        console.print()
        console.print("[heading]File references:[/heading]")
        console.print("  [muted]@filename[/muted]      Fuzzy-search files in cwd")
        console.print("  [muted]@path/to/[/muted]      Browse a directory")
        console.print()

    def _show_stats(self) -> None:
        """Show session statistics."""
        console.print(self._agent_session.print_stats())

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
        """Save conversation history to <work_dir>/.history/."""
        path = self._agent_session.save_history()
        console.print(f"[muted]History saved to {path}[/muted]")
