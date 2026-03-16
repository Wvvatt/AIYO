"""File system tools: read, write, edit, list, glob, grep."""

import fnmatch
import re
from pathlib import Path

from ._sandbox import safe_path

_MAX_LINES = 1000
_MAX_BYTES = 100_000
_MAX_LINE_LEN = 2000


async def read_file(path: str, line_offset: int = 1, n_lines: int = _MAX_LINES) -> str:
    """Read and return the text content of a file inside the workspace.

    Returns up to n_lines lines starting from line_offset (1-based).
    Lines longer than 2000 characters are truncated. Caps at 100 KB total.

    Args:
        path: Path relative to the workspace (or absolute within it).
        line_offset: First line to return (1-based, default 1).
        n_lines: Maximum number of lines to return (default 1000).
    """
    # Ensure integer types for line_offset and n_lines
    try:
        line_offset_int = int(line_offset)
        n_lines_int = int(n_lines)
    except (ValueError, TypeError):
        return f"Error: line_offset and n_lines must be integers, got {line_offset!r}, {n_lines!r}"
    
    try:
        p = safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.exists():
        return f"Error: file '{path}' not found."
    if not p.is_file():
        return f"Error: '{path}' is not a file."
    try:
        lines = p.read_bytes().decode("utf-8", errors="replace").splitlines()
    except PermissionError:
        return f"Error: no read permission for '{path}'."

    start = max(0, line_offset_int - 1)
    selected = lines[start : start + n_lines_int]

    result_lines: list[str] = []
    total_bytes = 0
    for i, line in enumerate(selected, start=start + 1):
        if len(line) > _MAX_LINE_LEN:
            line = line[:_MAX_LINE_LEN] + f"  [truncated, {len(line)} chars]"
        formatted = f"{i:>6}\t{line}"
        total_bytes += len(formatted.encode())
        if total_bytes > _MAX_BYTES:
            result_lines.append("[output truncated at 100 KB]")
            break
        result_lines.append(formatted)

    total = len(lines)
    header = f"File: {path}  (showing lines {start + 1}–{start + len(result_lines)} of {total})\n"
    return header + "\n".join(result_lines)


async def write_file(path: str, content: str, mode: str = "overwrite") -> str:
    """Write text content to a file inside the workspace.

    Args:
        path: Path relative to the workspace (or absolute within it).
        content: Text content to write.
        mode: Either "overwrite" (replace the file) or "append" (add to end).
    """
    if mode not in ("overwrite", "append"):
        return f"Error: mode must be 'overwrite' or 'append', got '{mode}'."
    try:
        p = safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.parent.exists():
        return f"Error: parent directory '{p.parent}' does not exist."
    try:
        if mode == "overwrite":
            p.write_text(content, encoding="utf-8")
        else:
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        return f"Written {len(content.encode())} bytes to '{path}'."
    except PermissionError:
        return f"Error: no write permission for '{path}'."
    except OSError as e:
        return f"Error writing file: {e}"


async def str_replace_file(path: str, old_str: str, new_str: str) -> str:
    """Replace an exact string in a file inside the workspace.

    The old_str must match exactly once in the file. If it matches zero or
    multiple times, the operation is rejected with an explanation.

    Args:
        path: Path relative to the workspace (or absolute within it).
        old_str: The exact text to find and replace.
        new_str: The replacement text.
    """
    try:
        p = safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.exists():
        return f"Error: file '{path}' not found."
    try:
        original = p.read_text(encoding="utf-8")
    except PermissionError:
        return f"Error: no read permission for '{path}'."

    count = original.count(old_str)
    if count == 0:
        return "Error: old_str not found in file. No changes made."
    if count > 1:
        return (
            f"Error: old_str found {count} times in file. "
            "Provide more context to make it unique. No changes made."
        )

    updated = original.replace(old_str, new_str, 1)
    try:
        p.write_text(updated, encoding="utf-8")
    except PermissionError:
        return f"Error: no write permission for '{path}'."

    return f"Replaced 1 occurrence in '{path}'."


async def list_directory(path: str = ".") -> str:
    """List files and directories at a path inside the workspace.

    Args:
        path: Directory path relative to the workspace (default: workspace root).
    """
    try:
        d = safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    try:
        entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [f"{'DIR ' if e.is_dir() else 'FILE'} {e.name}" for e in entries]
        return "\n".join(lines) if lines else "(empty directory)"
    except FileNotFoundError:
        return f"Error: directory '{path}' not found."


async def glob_files(pattern: str, directory: str = ".") -> str:
    """Find files and directories matching a glob pattern inside the workspace.

    Searches within the given directory. Returns up to 1000 matches, sorted.

    Args:
        pattern: Glob pattern, e.g. "**/*.py", "src/*.ts", "*.md".
        directory: Root directory relative to the workspace (default: workspace root).
    """
    try:
        base = safe_path(directory)
    except ValueError as e:
        return f"Error: {e}"
    if not base.exists():
        return f"Error: directory '{directory}' not found."
    if not base.is_dir():
        return f"Error: '{directory}' is not a directory."

    try:
        matches = sorted(str(p) for p in base.glob(pattern))
    except Exception as e:
        return f"Error: {e}"

    if not matches:
        return f"No files matched pattern '{pattern}' in '{directory}'."

    cap = 1000
    lines = matches[:cap]
    suffix = f"\n[...truncated at {cap} results]" if len(matches) > cap else ""
    return "\n".join(lines) + suffix


async def grep_files(
    pattern: str,
    path: str = ".",
    file_glob: str = "*",
    ignore_case: bool = False,
    context_lines: int = 0,
) -> str:
    """Search file contents for lines matching a regex pattern.

    Walks the given path (file or directory) and reports matching lines with
    their file path and line number. Returns up to 200 matches.

    Args:
        pattern: Python regex pattern to search for.
        path: File or directory to search (default: current directory).
        file_glob: Filename glob filter, e.g. "*.py" (default: "*").
        ignore_case: If true, match case-insensitively (default false).
        context_lines: Number of lines of context before and after each match (default 0).
    """
    # Ensure integer type for context_lines
    try:
        context_lines_int = int(context_lines)
    except (ValueError, TypeError):
        return f"Error: context_lines must be an integer, got {context_lines!r}"
    
    try:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    try:
        target = safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not target.exists():
        return f"Error: path '{path}' not found."

    files: list[Path] = []
    if target.is_file():
        files = [target]
    else:
        files = [p for p in target.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name, file_glob)]

    results: list[str] = []
    cap = 200

    for file in sorted(files):
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except (PermissionError, OSError):
            continue

        for lineno, line in enumerate(lines, start=1):
            if regex.search(line):
                if context_lines_int > 0:
                    lo = max(0, lineno - 1 - context_lines_int)
                    hi = min(len(lines), lineno + context_lines_int)
                    for ctx_i, ctx_line in enumerate(lines[lo:hi], start=lo + 1):
                        sep = ":" if ctx_i == lineno else "-"
                        results.append(f"{file}:{ctx_i}{sep}{ctx_line}")
                    results.append("--")
                else:
                    results.append(f"{file}:{lineno}:{line}")

                if len(results) >= cap:
                    results.append(f"[truncated at {cap} results]")
                    return "\n".join(results)

    return "\n".join(results) if results else f"No matches for '{pattern}' in '{path}'."
