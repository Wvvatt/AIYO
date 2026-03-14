"""Interactive prompt for shell UI."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from hashlib import md5
from pathlib import Path
from typing import Any, Literal, override

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    FuzzyCompleter,
    WordCompleter,
    merge_completers,
)
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_completions, has_focus
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import ConditionalContainer, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from aiyo.bridge import ModelCapability
from aiyo.ui.shell.console import console
from aiyo.utils.slashcmd import SlashCommand

PROMPT_SYMBOL = "✨"
PROMPT_SYMBOL_SHELL = "$"
PROMPT_SYMBOL_THINKING = "💫"
PROMPT_SYMBOL_PLAN = "📋"


class SlashCommandCompleter(Completer):
    """Completer for slash commands."""
    
    def __init__(self, available_commands: Sequence[SlashCommand[Any]]) -> None:
        super().__init__()
        self._available_commands = list(available_commands)
        self._command_lookup: dict[str, SlashCommand[Any]] = {}
        words: list[str] = []
        
        for cmd in sorted(self._available_commands, key=lambda c: c.name):
            if cmd.name not in self._command_lookup:
                self._command_lookup[cmd.name] = cmd
                words.append(cmd.name)
            for alias in cmd.aliases:
                if alias not in self._command_lookup:
                    self._command_lookup[alias] = cmd
                    words.append(alias)
        
        self._word_pattern = re.compile(r"[^\s]+")
        self._fuzzy_pattern = r"^[^\s]*"
        self._word_completer = WordCompleter(words, WORD=False, pattern=self._word_pattern)
        self._fuzzy = FuzzyCompleter(self._word_completer, WORD=False, pattern=self._fuzzy_pattern)
    
    @staticmethod
    def should_complete(document: Document) -> bool:
        """Return whether slash command completion should be active."""
        text = document.text_before_cursor
        if document.text_after_cursor.strip():
            return False
        last_space = text.rfind(" ")
        token = text[last_space + 1:]
        prefix = text[: last_space + 1] if last_space != -1 else ""
        return not prefix.strip() and token.startswith("/")
    
    @override
    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        if not self.should_complete(document):
            return
        text = document.text_before_cursor
        last_space = text.rfind(" ")
        token = text[last_space + 1:]
        
        typed = token[1:]
        if typed and typed in self._command_lookup:
            return
        mention_doc = Document(text=typed, cursor_position=len(typed))
        candidates = list(self._fuzzy.get_completions(mention_doc, complete_event))
        
        seen: set[str] = set()
        
        for candidate in candidates:
            cmd = self._command_lookup.get(candidate.text)
            if not cmd:
                continue
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            yield Completion(
                text=f"/{cmd.name}",
                start_position=-len(token),
                display=f"/{cmd.name}",
                display_meta=cmd.description,
            )


class LocalFileMentionCompleter(Completer):
    """Offer fuzzy `@` path completion by indexing workspace files."""
    
    _FRAGMENT_PATTERN = re.compile(r"[^\s@]+")
    _TRIGGER_GUARDS = frozenset((".", "-", "_", "`", "'", '"', ":", "@", "#", "~"))
    _IGNORED_NAMES = frozenset([
        ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
        ".pytest_cache", ".mypy_cache", ".tox", "dist", "build", ".idea",
        ".vscode", ".DS_Store", "*.pyc", "*.pyo", "*.egg-info", ".coverage",
        "htmlcov", ".next", ".nuxt", ".turbo",
    ])
    
    def __init__(
        self,
        root: Path,
        *,
        refresh_interval: float = 2.0,
        limit: int = 1000,
    ) -> None:
        self._root = root
        self._refresh_interval = refresh_interval
        self._limit = limit
        self._cache_time: float = 0.0
        self._cached_paths: list[str] = []
        self._fragment_hint: str | None = None
        
        self._word_completer = WordCompleter(
            self._get_paths,
            WORD=False,
            pattern=self._FRAGMENT_PATTERN,
        )
        
        self._fuzzy = FuzzyCompleter(
            self._word_completer,
            WORD=False,
            pattern=r"^[^\s@]*",
        )
    
    @classmethod
    def _is_ignored(cls, name: str) -> bool:
        if not name:
            return True
        if name.startswith(".") and name != ".":
            if name in (".", ".."):
                return False
            # Allow hidden files but not directories like .git
            if name in cls._IGNORED_NAMES:
                return True
        if name in cls._IGNORED_NAMES:
            return True
        if any(name.endswith(ext) for ext in [".pyc", ".pyo", ".egg-info"]):
            return True
        return False
    
    def _get_paths(self) -> list[str]:
        fragment = self._fragment_hint or ""
        if "/" not in fragment and len(fragment) < 3:
            return self._get_top_level_paths()
        return self._get_deep_paths()
    
    def _get_top_level_paths(self) -> list[str]:
        import time
        
        now = time.monotonic()
        if now - self._cache_time <= self._refresh_interval:
            return self._cached_paths
        
        entries: list[str] = []
        try:
            for entry in sorted(self._root.iterdir(), key=lambda p: p.name):
                name = entry.name
                if self._is_ignored(name):
                    continue
                entries.append(f"{name}/" if entry.is_dir() else name)
                if len(entries) >= self._limit:
                    break
        except OSError:
            pass
        
        self._cached_paths = entries
        self._cache_time = now
        return self._cached_paths
    
    def _get_deep_paths(self) -> list[str]:
        import time
        
        now = time.monotonic()
        if now - self._cache_time <= self._refresh_interval:
            return self._cached_paths
        
        paths: list[str] = []
        try:
            for current_root, dirs, files in os.walk(self._root):
                relative_root = Path(current_root).relative_to(self._root)
                
                # Prevent descending into ignored directories
                dirs[:] = sorted(d for d in dirs if not self._is_ignored(d))
                
                if relative_root.parts and any(
                    self._is_ignored(part) for part in relative_root.parts
                ):
                    dirs[:] = []
                    continue
                
                if relative_root.parts:
                    paths.append(relative_root.as_posix() + "/")
                    if len(paths) >= self._limit:
                        break
                
                for file_name in sorted(files):
                    if self._is_ignored(file_name):
                        continue
                    relative = (relative_root / file_name).as_posix()
                    if not relative:
                        continue
                    paths.append(relative)
                    if len(paths) >= self._limit:
                        break
                
                if len(paths) >= self._limit:
                    break
        except OSError:
            pass
        
        self._cached_paths = paths
        self._cache_time = now
        return self._cached_paths
    
    @staticmethod
    def _extract_fragment(text: str) -> str | None:
        index = text.rfind("@")
        if index == -1:
            return None
        
        if index > 0:
            prev = text[index - 1]
            if prev.isalnum() or prev in LocalFileMentionCompleter._TRIGGER_GUARDS:
                return None
        
        fragment = text[index + 1:]
        if not fragment:
            return ""
        
        if any(ch.isspace() for ch in fragment):
            return None
        
        return fragment
    
    def _is_completed_file(self, fragment: str) -> bool:
        candidate = fragment.rstrip("/")
        if not candidate:
            return False
        try:
            return (self._root / candidate).is_file()
        except OSError:
            return False
    
    @override
    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        fragment = self._extract_fragment(document.text_before_cursor)
        if fragment is None:
            return
        if self._is_completed_file(fragment):
            return
        
        mention_doc = Document(text=fragment, cursor_position=len(fragment))
        self._fragment_hint = fragment
        try:
            candidates = list(self._fuzzy.get_completions(mention_doc, complete_event))
            
            # Re-rank: prefer basename matches
            frag_lower = fragment.lower()
            
            def _rank(c: Completion) -> tuple[int, ...]:
                path = c.text
                base = path.rstrip("/").split("/")[-1].lower()
                if base.startswith(frag_lower):
                    cat = 0
                elif frag_lower in base:
                    cat = 1
                else:
                    cat = 2
                return (cat,)
            
            candidates.sort(key=_rank)
            yield from candidates
        finally:
            self._fragment_hint = None


class PromptMode(Enum):
    AGENT = "agent"
    SHELL = "shell"
    
    def toggle(self) -> "PromptMode":
        return PromptMode.SHELL if self == PromptMode.AGENT else PromptMode.AGENT
    
    def __str__(self) -> str:
        return self.value


@dataclass
class UserInput:
    """User input from prompt."""
    mode: PromptMode
    command: str
    resolved_command: str
    content: list[Any]  # ContentPart list
    
    def __str__(self) -> str:
        return self.command
    
    def __bool__(self) -> bool:
        return bool(self.command)


@dataclass(slots=True)
class _ToastEntry:
    topic: str | None
    message: str
    expires_at: float


_toast_queues: dict[Literal["left", "right"], list[_ToastEntry]] = {
    "left": [],
    "right": [],
}


def toast(
    message: str,
    duration: float = 5.0,
    topic: str | None = None,
    immediate: bool = False,
    position: Literal["left", "right"] = "left",
) -> None:
    """Show a toast notification."""
    import time
    
    queue = _toast_queues[position]
    entry = _ToastEntry(topic=topic, message=message, expires_at=time.monotonic() + duration)
    
    if topic is not None:
        # Remove existing toasts with the same topic
        queue[:] = [e for e in queue if e.topic != topic]
    
    if immediate:
        queue.insert(0, entry)
    else:
        queue.append(entry)


def _current_toast(position: Literal["left", "right"] = "left") -> _ToastEntry | None:
    """Get the current toast to display."""
    import time
    
    queue = _toast_queues[position]
    now = time.monotonic()
    
    # Remove expired toasts
    while queue and queue[0].expires_at <= now:
        queue.pop(0)
    
    return queue[0] if queue else None


class CustomPromptSession:
    """Custom prompt session with rich features."""
    
    def __init__(
        self,
        *,
        status_provider: Callable[[], Any],
        model_capabilities: set[ModelCapability],
        model_name: str | None,
        thinking: bool,
        agent_mode_slash_commands: Sequence[SlashCommand[Any]],
        shell_mode_slash_commands: Sequence[SlashCommand[Any]],
        editor_command_provider: Callable[[], str] = lambda: "",
        plan_mode_toggle_callback: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._status_provider = status_provider
        self._model_capabilities = model_capabilities
        self._model_name = model_name
        self._thinking = thinking
        self._editor_command_provider = editor_command_provider
        self._plan_mode_toggle_callback = plan_mode_toggle_callback
        self._mode: PromptMode = PromptMode.AGENT
        
        # Build completers
        self._agent_mode_completer = merge_completers(
            [
                SlashCommandCompleter(agent_mode_slash_commands),
                LocalFileMentionCompleter(Path.cwd()),
            ],
            deduplicate=True,
        )
        self._shell_mode_completer = SlashCommandCompleter(shell_mode_slash_commands)
        
        # Key bindings
        self._kb = KeyBindings()
        self._setup_key_bindings()
        
        # Create prompt session
        history = InMemoryHistory()
        
        style = Style.from_dict({
            "prompt": "ansicyan bold",
            "prompt.shell": "ansiyellow",
        })
        
        self._session: PromptSession[str] = PromptSession(
            completer=self._agent_mode_completer,
            complete_while_typing=True,
            key_bindings=self._kb,
            style=style,
            history=history,
            multiline=True,
        )
    
    def _setup_key_bindings(self) -> None:
        """Setup custom key bindings."""
        
        @self._kb.add("c-x")
        def _toggle_mode(event: KeyPressEvent) -> None:
            """Toggle between agent and shell mode."""
            self._mode = self._mode.toggle()
            # Update completer based on mode
            if self._mode == PromptMode.SHELL:
                self._session.completer = self._shell_mode_completer
            else:
                self._session.completer = self._agent_mode_completer
        
        @self._kb.add("c-o")
        def _open_editor(event: KeyPressEvent) -> None:
            """Open external editor."""
            event.app.current_buffer.open_in_editor(self._session)
        
        @self._kb.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:
            """Handle Ctrl+C."""
            event.app.exit(exception=KeyboardInterrupt)
        
        @self._kb.add("c-d")
        def _exit(event: KeyPressEvent) -> None:
            """Handle Ctrl+D."""
            if not event.app.current_buffer.text:
                event.app.exit(exception=EOFError)
    
    def _get_prompt_text(self) -> AnyFormattedText:
        """Get the prompt text based on current mode."""
        if self._mode == PromptMode.SHELL:
            return [("class:prompt.shell", PROMPT_SYMBOL_SHELL + " ")]
        symbol = PROMPT_SYMBOL_THINKING if self._thinking else PROMPT_SYMBOL
        return [("class:prompt", symbol + " ")]
    
    async def prompt(self) -> UserInput | None:
        """Show prompt and get user input."""
        try:
            with patch_stdout():
                text = await self._session.prompt_async(
                    self._get_prompt_text(),
                    rprompt=self._get_rprompt(),
                )
            
            if not text.strip():
                return None
            
            # Create simple content (just text for now)
            content = [{"type": "text", "content": text}]
            
            return UserInput(
                mode=self._mode,
                command=text,
                resolved_command=text,
                content=content,
            )
        except KeyboardInterrupt:
            raise
        except EOFError:
            raise
    
    def _get_rprompt(self) -> AnyFormattedText:
        """Get the right-side prompt (status)."""
        status = self._status_provider()
        if status.context_tokens > 0:
            pct = int(status.context_usage * 100)
            return f" {pct}% "
        return ""
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
