"""Prompt completer for slash commands and file paths."""

import os
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


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
        "/skills": "List available skills",
        "/exit": "Exit",
    }

    def __init__(self, skill_commands: dict[str, str] | None = None) -> None:
        self._commands = dict(self.COMMANDS)
        self._skill_commands = dict(skill_commands or {})  # name -> description

    # Directories to skip during recursive file search
    _SKIP_DIRS = frozenset(
        {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}
    )

    @staticmethod
    def _fuzzy_match(pattern: str, text: str) -> bool:
        """Return True if all chars of pattern appear in text in order."""
        it = iter(text)
        return all(c in it for c in pattern)

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # Slash commands: only when `/` is the first char and no spaces yet
        if text.startswith("/") and " " not in text:
            for cmd, desc in self._commands.items():
                if self._fuzzy_match(text, cmd):
                    yield Completion(cmd, start_position=-len(text), display_meta=desc)
            return

        # Skill commands: `#` anywhere (no spaces after `#`)
        hash_idx = text.rfind("#")
        if hash_idx != -1:
            after_hash = text[hash_idx + 1 :]
            if " " not in after_hash:
                query = after_hash.lower()
                for name, desc in self._skill_commands.items():
                    if self._fuzzy_match(query, name):
                        completion = "#" + name
                        yield Completion(
                            completion,
                            start_position=-(len(after_hash) + 1),
                            display_meta=desc,
                        )
                return

        # Path completion after @
        yield from self._at_path_completions(text)

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
        """Recursively search cwd for files and directories whose name fuzzy-matches query."""
        cwd = Path(".")
        pattern = query.lower()
        matches: list[tuple[Path, bool]] = []

        for path in cwd.rglob("*"):
            if any(part in self._SKIP_DIRS for part in path.parts):
                continue
            if not (path.is_file() or path.is_dir()):
                continue
            if pattern and not self._fuzzy_match(pattern, path.name.lower()):
                continue
            is_dir = path.is_dir()
            matches.append((path, is_dir))
            if len(matches) >= 50:  # cap results
                break

        for path, is_dir in sorted(matches, key=lambda x: x[0].name):
            rel = str(path)
            completion = "@" + rel + ("/" if is_dir else "")
            yield Completion(
                completion,
                start_position=-(len(query) + 1),
                display=path.name + ("/" if is_dir else ""),
                display_meta="dir" if is_dir else str(path.parent),
            )
