"""Interactive shell UI — Claude Code style."""

from __future__ import annotations

import asyncio
import re
import signal
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.markdown import Markdown
from rich.status import Status
from rich.table import Table

from aiyo.agent.agent import Agent
from aiyo.config import settings
from aiyo.tools import WRITE_TOOLS
from aiyo.tools.skills import get_skill_loader

try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []

from .completer import AiyoCompleter
from .middleware import ToolDisplayMiddleware
from .theme import CODE_THEME, SPINNER_TEXT, console, format_tokens, get_palette


class ShellUI:
    """Interactive shell UI in Claude Code style."""

    _PASTE_THRESHOLD = 5  # lines; below this paste inline, above show placeholder

    def __init__(self, agent: Agent | None = None) -> None:
        self._paste_store: dict[str, str] = {}
        self._tool_display_middleware = ToolDisplayMiddleware(
            interactive_callback=self._handle_interactive_questions
        )
        self._agent_session = agent or Agent(
            extra_tools=WRITE_TOOLS + EXT_TOOLS,
            extra_middleware=[
                self._tool_display_middleware,
            ],
        )
        self._model_name = self._agent_session.model_name
        self._running = False
        self._last_turn_duration: float = 0.0
        self._palette = get_palette()
        self._current_status: Status | None = None

        # Setup prompt session
        kb = self._setup_keybindings()
        style = Style.from_dict(
            {
                "bottom-toolbar": "noreverse",
            }
        )
        skill_loader = get_skill_loader()
        skill_commands = {
            name: (skill.description if (skill := skill_loader.get_skill(name)) else "")
            for name in skill_loader.list_skills()
        }
        self._skill_names = set(skill_commands.keys())

        self._prompt_session = PromptSession(
            message="> ",
            bottom_toolbar=self._toolbar,
            completer=AiyoCompleter(skill_commands=skill_commands),
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

        @kb.add("#")
        def hash_complete(event):
            buf = event.app.current_buffer
            buf.insert_text("#")
            buf.start_completion()

        @kb.add("s-tab")  # Shift-Tab to toggle plan mode
        def toggle_plan_mode(event):
            if self._agent_session.toggle_plan_mode():
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
        mode = "[PLAN MODE]" if self._agent_session.plan_mode else "[NORMAL MODE]"
        parts.append(f"<span fg='{self._palette['accent']}'>{mode}</span> (⇧+Tab)")
        parts.append(f"model: {self._model_name}")
        parts.append(f"tokens: {tokens_in}/{tokens_out}")
        if duration > 0:
            parts.append(f"last: {duration:.1f}s")
        parts.append("/help")
        parts.append("@:mention file #:use skill")

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

        # Wrap @file references in <reminder-file> tags
        text = self._wrap_at_refs(text)

        # Wrap #skill references in <reminder-skill> tags
        text = self._wrap_skill_refs(text)

        for placeholder, content in self._paste_store.items():
            text = text.replace(placeholder, content)
        self._paste_store.clear()

        await self._chat(text)

    def _wrap_at_refs(self, text: str) -> str:
        """Wrap @file references in <reminder-file> tags.

        Converts @filename or @path/to/file to <reminder-file>filename</reminder-file>,
        so the LLM can clearly identify file references.
        """

        def replace_at_ref(match: re.Match) -> str:
            path = match.group(1)
            return f"<reminder-file>{path}</reminder-file>"

        # Match @ followed by path characters (no spaces)
        return re.sub(r"@([^\s]+)", replace_at_ref, text)

    def _wrap_skill_refs(self, text: str) -> str:
        """Wrap #skill references in <reminder-skill> tags.

        Converts #skill-name to <reminder-skill>skill-name</reminder-skill>,
        so the LLM can clearly identify skill references.
        """

        def replace_skill_ref(match: re.Match) -> str:
            skill_name = match.group(1)
            return f"<reminder-skill>{skill_name}</reminder-skill>"

        # Match # followed by skill name (word chars, -, _)
        return re.sub(r"#([\w-]+)", replace_skill_ref, text)

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
            case "/skills":
                self._show_skills()
            case _:
                console.print(f"[error]Unknown command: {cmd}[/error]")

    async def _chat(self, message: str) -> None:
        """Chat with agent and display response."""
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()

        def _on_sigint():
            if task:
                task.cancel()

        loop.add_signal_handler(signal.SIGINT, _on_sigint)
        try:
            with Status(SPINNER_TEXT, console=console, spinner="dots") as status:
                self._current_status = status
                response = await self._agent_session.chat(message)
                self._current_status = None
        except asyncio.CancelledError:
            console.print("\n[muted]Cancelled.[/muted]")
            return
        except Exception as e:
            error_msg = str(e)
            if "Connection error" in error_msg or "ConnectError" in error_msg:
                console.print("\n[error]Connection failed[/error]")
                console.print("[muted]Please check:[/muted]")
                console.print("  [muted]1. Your network connection[/muted]")
                console.print("  [muted]2. Set HTTP_PROXY/HTTPS_PROXY if behind a proxy[/muted]")
                console.print("  [muted]3. Your API key configuration[/muted]")
            else:
                console.print(f"\n[error]Error: {error_msg}[/error]")
            return
        finally:
            loop.remove_signal_handler(signal.SIGINT)

        self._last_turn_duration = time.monotonic() - t0

        if response:
            console.print()
            console.print(Markdown(response, code_theme=CODE_THEME))
        console.print()

    async def _handle_interactive_questions(
        self, questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Handle ask_user_question by pausing spinner and showing interactive UI.

        This is called by ToolDisplayMiddleware when ask_user_question is executed.
        The spinner is paused during user interaction to avoid display conflicts.
        """
        # Pause spinner if active
        if self._current_status is not None:
            self._current_status.stop()

        try:
            # Use middleware's internal handler
            result = await self._tool_display_middleware._handle_ask_user_question(questions)
            return result
        finally:
            # Resume spinner if it was active
            if self._current_status is not None:
                self._current_status.start()

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
        console.print("  [muted]/skills[/muted]          List available skills")
        console.print("  [muted]/exit[/muted]             Exit")
        console.print()
        console.print("[heading]Keys:[/heading]")
        console.print("  [muted]Enter[/muted]     Submit input")
        console.print("  [muted]Ctrl-C[/muted]    Cancel running task (or clear input)")
        console.print("  [muted]Ctrl-D[/muted]    Exit")
        console.print()
        console.print("[heading]Shortcuts:[/heading]")
        console.print("  [muted]@filename[/muted]      Reference file (fuzzy search)")
        console.print("  [muted]#skill[/muted]          Invoke a skill (use /skills to list)")
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

    def _show_skills(self) -> None:
        """List all currently available skills."""
        skill_loader = get_skill_loader()
        skills = skill_loader.list_skills()
        if not skills:
            console.print("[muted]No skills available.[/muted]")
            return

        groups: dict[str, list[tuple[str, str]]] = {}
        for name in skills:
            skill = skill_loader.get_skill(name)
            if skill:
                parent = skill.path.parent.name if skill.path.parent.name != "skills" else "builtin"
                groups.setdefault(parent, []).append((name, skill.description))

        console.print()
        console.print("[heading]Available skills:[/heading]")
        console.print()

        for group_name in sorted(groups.keys()):
            skill_list = groups[group_name]
            table = Table(
                show_header=False,
                box=None,
                padding=(0, 2, 0, 0),
                collapse_padding=True,
            )
            table.add_column("name", style="accent", min_width=20)
            table.add_column("description", style="")

            for name, desc in sorted(skill_list):
                table.add_row(f"#{name}", desc)

            console.print(f"[muted]{group_name}:[/muted]")
            console.print(table)
            console.print()

    def _save_history(self) -> None:
        """Save conversation history to <work_dir>/.history/."""
        path = self._agent_session.save_history()
        console.print(f"[muted]History saved to {path}[/muted]")
