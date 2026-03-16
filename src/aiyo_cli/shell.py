"""Interactive shell UI — Claude Code style."""

from __future__ import annotations

import asyncio
import difflib
import os
import signal
import time
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
from rich.syntax import Syntax
from rich.theme import Theme

from aiyo import DEFAULT_TOOLS, Middleware, Session

# ── Theme ──────────────────────────────────────────────────────────────────
_PALETTE = {
    "accent": "#5fd7ff",  # tool names, inline code, welcome
    "muted": "#666666",  # system messages, dim text
    "error": "#ff5555",  # errors
    "heading": "bold",  # section headers
}
THEME = Theme(
    {
        "tool": f"bold {_PALETTE['accent']}",
        "muted": _PALETTE["muted"],
        "error": _PALETTE["error"],
        "heading": _PALETTE["heading"],
        "markdown.code": f"bold {_PALETTE['accent']}",
    }
)
DIFF_THEME = "monokai"
TOOLBAR_BG = "#1e1e2e"
TOOLBAR_FG = "#cdd6f4"
SPINNER_TEXT = "[muted]Aiyo...[/muted]"

console = Console(theme=THEME)


class ToolDisplayMiddleware(Middleware):
    """Print tool calls to the console using Rich."""

    def after_tool_call(self, tool_name: str, tool_args: dict, result: object) -> object:
        name = "".join(p.capitalize() for p in tool_name.split("_"))
        match tool_name:
            case "todo":
                console.print(f"[tool]{name}[/tool]\n[muted]{result}[/muted]")
            case "think":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('thought', '')}[/muted]")
            case "read_file" | "write_file" | "str_replace_file":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('path', '')}[/muted]")
            case "glob_files":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('pattern', '')}[/muted]")
            case "list_directory":
                console.print(
                    f"[tool]{name}[/tool] [muted]{tool_args.get('relative_path', '.')}[/muted]"
                )
            case "run_shell_command":
                cmd = tool_args.get("command", "")
                console.print(f"[tool]{name}[/tool] [muted]{cmd[:80]}[/muted]")
            case "load_skill":
                console.print(f"[tool]{name}[/tool] [muted]{tool_args.get('name', '')}[/muted]")
            case _:
                console.print(f"[tool]{name}[/tool]")
        return result


class DiffMiddleware(Middleware):
    """Capture file diffs during a turn and print them after the response."""

    _WRITE_TOOLS = frozenset({"write_file", "str_replace_file"})

    def __init__(self) -> None:
        self._old: dict[str, str] = {}
        self._pending: list[str] = []

    def before_chat(self, user_message: str) -> str:
        self._pending.clear()
        return user_message

    def before_tool_call(self, tool_name: str, tool_args: dict) -> tuple[str, dict]:
        if tool_name in self._WRITE_TOOLS:
            path = tool_args.get("path", "")
            if path:
                try:
                    p = Path(path)
                    self._old[path] = p.read_text(encoding="utf-8") if p.exists() else ""
                except OSError:
                    self._old[path] = ""
        return tool_name, tool_args

    def after_tool_call(self, tool_name: str, tool_args: dict, result: object) -> object:
        if tool_name not in self._WRITE_TOOLS:
            return result
        path = tool_args.get("path", "")
        if not path or (isinstance(result, str) and result.startswith("Error:")):
            self._old.pop(path, None)
            return result

        old = self._old.pop(path, "")
        try:
            new = Path(path).read_text(encoding="utf-8")
        except OSError:
            return result

        if old == new:
            return result

        diff = list(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        if diff:
            self._pending.append("\n".join(diff))
        return result

    def after_chat(self, response: str) -> str:
        if not self._pending:
            return response
        for diff_str in self._pending:
            console.print(Syntax(diff_str, "diff", theme=DIFF_THEME))
        return response


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
    _SKIP_DIRS = frozenset(
        {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}
    )

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
        self._agent_session = session or Session(
            DEFAULT_TOOLS, extra_middleware=[ToolDisplayMiddleware(), DiffMiddleware()]
        )
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
        parts.append("/help for commands")

        return HTML(f" <style bg='{TOOLBAR_BG}' fg='{TOOLBAR_FG}'>{' | '.join(parts)}</style>")

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
                result = self._agent_session.compact()
                if result:
                    console.print(f"[muted]{result}[/muted]")
            case "/save":
                self._save_history()
            case "/debug":
                self._agent_session.set_debug(True)
                console.print("[muted]Debug mode enabled.[/muted]")
            case "/nodebug":
                self._agent_session.set_debug(False)
                console.print("[muted]Debug mode disabled.[/muted]")
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
            console.print(Markdown(response))
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
            " ╚═╝  ╚═╝╚═╝   ╚═╝    ╚═════╝ "
            "[/tool]"
        )
        console.print(banner)
        console.print(f"[muted]{self._model_name}[/muted]\n")

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
        console.print("  [muted]/debug[/muted]           Enable debug logging")
        console.print("  [muted]/nodebug[/muted]         Disable debug logging")
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
