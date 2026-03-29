"""File system tools: read, write, edit, list, glob, grep.

Implementation follows kimi-cli's file tools exactly:
- Complete file type detection via magic bytes and extension
- Streaming async file operations
- ripgrep-based grep implementation
- Security validations matching kimi-cli behavior
"""

from __future__ import annotations

import asyncio
import fnmatch
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from ._sandbox import safe_path
from .exceptions import ToolError

# Import ripgrepy for grep implementation
try:
    import ripgrepy
except ImportError:
    ripgrepy = None

_MAX_LINES = 1000
_MAX_BYTES = 100_000
_MAX_LINE_LENGTH = 2000
_MEDIA_SNIFF_BYTES = 512

# Extra MIME types (from kimi-cli)
_EXTRA_MIME_TYPES = {
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".mkv": "video/x-matroska",
    ".m4v": "video/x-m4v",
    ".3gp": "video/3gpp",
    ".3g2": "video/3gpp2",
    ".ts": "text/typescript",
    ".tsx": "text/typescript",
    ".mts": "text/typescript",
    ".cts": "text/typescript",
}

for suffix, mime_type in _EXTRA_MIME_TYPES.items():
    mimetypes.add_type(mime_type, suffix)

_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
    ".svgz": "image/svg+xml",
}

_VIDEO_MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
    ".flv": "video/x-flv",
    ".3gp": "video/3gpp",
    ".3g2": "video/3gpp2",
}

_TEXT_MIME_BY_SUFFIX = {
    ".svg": "image/svg+xml",
}

_ASF_HEADER = b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c"

_FTYP_IMAGE_BRANDS = {
    "avif": "image/avif",
    "avis": "image/avif",
    "heic": "image/heic",
    "heif": "image/heif",
    "heix": "image/heif",
    "hevc": "image/heic",
    "mif1": "image/heif",
    "msf1": "image/heif",
}

_FTYP_VIDEO_BRANDS = {
    "isom": "video/mp4",
    "iso2": "video/mp4",
    "iso5": "video/mp4",
    "mp41": "video/mp4",
    "mp42": "video/mp4",
    "avc1": "video/mp4",
    "mp4v": "video/mp4",
    "m4v": "video/x-m4v",
    "qt": "video/quicktime",
    "3gp4": "video/3gpp",
    "3gp5": "video/3gpp",
    "3gp6": "video/3gpp",
    "3gp7": "video/3gpp",
    "3g2": "video/3gpp2",
}

_NON_TEXT_SUFFIXES = {
    ".icns",
    ".psd",
    ".ai",
    ".eps",
    ".pdf",
    ".doc",
    ".docx",
    ".dot",
    ".dotx",
    ".rtf",
    ".odt",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlt",
    ".xltx",
    ".xltm",
    ".ods",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".odp",
    ".pages",
    ".numbers",
    ".key",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".zst",
    ".lz",
    ".lz4",
    ".br",
    ".cab",
    ".ar",
    ".deb",
    ".rpm",
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".aac",
    ".m4a",
    ".wma",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".apk",
    ".ipa",
    ".jar",
    ".class",
    ".pyc",
    ".pyo",
    ".wasm",
    ".dmg",
    ".iso",
    ".img",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".db3",
}

_FILE_WRITE_LOCKS: dict[str, asyncio.Lock] = {}


def _get_file_lock(path: Path) -> asyncio.Lock:
    """Get (or create) process-local write lock for a canonical file path."""
    key = str(path.resolve(strict=False))
    lock = _FILE_WRITE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _FILE_WRITE_LOCKS[key] = lock
    return lock


def _sniff_ftyp_brand(header: bytes) -> str | None:
    """Extract ftyp brand from ISO base media file format header."""
    if len(header) < 12 or header[4:8] != b"ftyp":
        return None
    brand = header[8:12].decode("ascii", errors="ignore").lower()
    return brand.strip()


def _sniff_media_from_magic(data: bytes) -> FileType | None:
    """Detect file type from magic bytes."""
    header = data[:_MEDIA_SNIFF_BYTES]

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileType(kind="image", mime_type="image/png")
    if header.startswith(b"\xff\xd8\xff"):
        return FileType(kind="image", mime_type="image/jpeg")
    if header.startswith((b"GIF87a", b"GIF89a")):
        return FileType(kind="image", mime_type="image/gif")
    if header.startswith(b"BM"):
        return FileType(kind="image", mime_type="image/bmp")
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return FileType(kind="image", mime_type="image/tiff")
    if header.startswith(b"\x00\x00\x01\x00"):
        return FileType(kind="image", mime_type="image/x-icon")
    if header.startswith(b"RIFF") and len(header) >= 12:
        chunk = header[8:12]
        if chunk == b"WEBP":
            return FileType(kind="image", mime_type="image/webp")
        if chunk == b"AVI ":
            return FileType(kind="video", mime_type="video/x-msvideo")
    if header.startswith(b"FLV"):
        return FileType(kind="video", mime_type="video/x-flv")
    if header.startswith(_ASF_HEADER):
        return FileType(kind="video", mime_type="video/x-ms-wmv")
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        lowered = header.lower()
        if b"webm" in lowered:
            return FileType(kind="video", mime_type="video/webm")
        if b"matroska" in lowered:
            return FileType(kind="video", mime_type="video/x-matroska")
    if brand := _sniff_ftyp_brand(header):
        if brand in _FTYP_IMAGE_BRANDS:
            return FileType(kind="image", mime_type=_FTYP_IMAGE_BRANDS[brand])
        if brand in _FTYP_VIDEO_BRANDS:
            return FileType(kind="video", mime_type=_FTYP_VIDEO_BRANDS[brand])
    return None


@dataclass(frozen=True)
class FileType:
    """Detected file type classification."""

    kind: Literal["text", "image", "video", "unknown"]
    mime_type: str = ""


def detect_file_type(path: str | PurePath, header: bytes | None = None) -> FileType:
    """Detect file type from extension and optionally from content.

    Exact implementation from kimi-cli.
    """
    suffix = PurePath(str(path)).suffix.lower()
    media_hint: FileType | None = None

    if suffix in _TEXT_MIME_BY_SUFFIX:
        media_hint = FileType(kind="text", mime_type=_TEXT_MIME_BY_SUFFIX[suffix])
    elif suffix in _IMAGE_MIME_BY_SUFFIX:
        media_hint = FileType(kind="image", mime_type=_IMAGE_MIME_BY_SUFFIX[suffix])
    elif suffix in _VIDEO_MIME_BY_SUFFIX:
        media_hint = FileType(kind="video", mime_type=_VIDEO_MIME_BY_SUFFIX[suffix])
    else:
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            if mime_type.startswith("image/"):
                media_hint = FileType(kind="image", mime_type=mime_type)
            elif mime_type.startswith("video/"):
                media_hint = FileType(kind="video", mime_type=mime_type)

    if media_hint and media_hint.kind in ("image", "video"):
        return media_hint

    if header is not None:
        sniffed = _sniff_media_from_magic(header)
        if sniffed:
            if media_hint and sniffed.kind != media_hint.kind:
                return FileType(kind="unknown", mime_type="")
            return sniffed
        # NUL bytes are a strong signal of binary content
        if b"\x00" in header:
            return FileType(kind="unknown", mime_type="")

    if media_hint:
        return media_hint
    if suffix in _NON_TEXT_SUFFIXES:
        return FileType(kind="unknown", mime_type="")
    return FileType(kind="text", mime_type="text/plain")


def _iter_files_with_symlinks(directory: Path) -> list[Path]:
    """Recursively list all files in directory, following symlinks.

    Uses Path.walk() with follow_symlinks=True (Python 3.12+) to properly
    handle symlinked directories inside the workspace.
    """
    results: list[Path] = []
    for dirpath, _dirnames, filenames in directory.walk(follow_symlinks=True):
        for name in filenames:
            results.append(dirpath / name)
    return results


def _truncate_line(line: str, max_len: int = _MAX_LINE_LENGTH) -> str:
    """Truncate a line if it exceeds max_len, adding ellipsis."""
    if len(line) <= max_len:
        return line
    return line[:max_len] + "..."


async def read_file(
    path: str,
    *,
    line_offset: int = 1,
    n_lines: int = _MAX_LINES,
) -> str:
    """Read and return the text content of a file inside the workspace.

    Implementation follows kimi-cli's ReadFile tool:
    - Returns up to n_lines lines starting from line_offset (1-based)
    - Lines longer than 2000 characters are truncated
    - Caps at 100 KB total
    - File type detection via magic bytes
    """
    # Validate parameters
    try:
        line_offset_int = int(line_offset)
        n_lines_int = int(n_lines)
    except (ValueError, TypeError) as e:
        raise ToolError(
            f"line_offset and n_lines must be integers, got {line_offset!r}, {n_lines!r}"
        ) from e

    if line_offset_int < 1:
        raise ToolError(f"line_offset must be >= 1, got {line_offset_int}")
    if n_lines_int < 1:
        raise ToolError(f"n_lines must be >= 1, got {n_lines_int}")

    try:
        p = safe_path(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not p.exists():
        raise ToolError(f"`{path}` does not exist.")
    if not p.is_file():
        raise ToolError(f"`{path}` is not a file.")

    # Check file type before reading
    try:
        file_size = p.stat().st_size
        with p.open("rb") as f:
            header = f.read(min(_MEDIA_SNIFF_BYTES, file_size))
    except PermissionError as e:
        raise ToolError(f"no read permission for '{path}'.") from e

    file_type = detect_file_type(p, header)

    if file_type.kind == "image":
        raise ToolError(
            f"`{path}` is an image file. Use other appropriate tools to read image files."
        )
    if file_type.kind == "video":
        raise ToolError(
            f"`{path}` is a video file. Use other appropriate tools to read video files."
        )
    if file_type.kind == "unknown":
        raise ToolError(
            f"`{path}` seems not readable. "
            "You may need to read it with proper shell commands, Python tools "
            "or MCP tools if available. "
            "If you read/operate it with Python, you MUST ensure that any "
            "third-party packages are installed in a virtual environment (venv)."
        )

    # Read file content with streaming
    lines: list[str] = []
    n_bytes = 0
    truncated_line_numbers: list[int] = []
    max_lines_reached = False
    max_bytes_reached = False
    current_line_no = 0

    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                current_line_no += 1
                if current_line_no < line_offset_int:
                    continue

                # Remove trailing newline for processing
                line = line.rstrip("\n\r")

                truncated = _truncate_line(line, _MAX_LINE_LENGTH)
                if truncated != line:
                    truncated_line_numbers.append(current_line_no)

                lines.append(truncated)
                n_bytes += len(truncated.encode("utf-8"))

                if len(lines) >= n_lines_int:
                    break
                if len(lines) >= _MAX_LINES:
                    max_lines_reached = True
                    break
                if n_bytes >= _MAX_BYTES:
                    max_bytes_reached = True
                    break
    except PermissionError as e:
        raise ToolError(f"no read permission for '{path}'.") from e

    # Format output with line numbers like `cat -n`
    lines_with_no: list[str] = []
    for line_num, line in zip(
        range(line_offset_int, line_offset_int + len(lines)), lines, strict=True
    ):
        # Use 6-digit line number width, right-aligned, with tab separator
        lines_with_no.append(f"{line_num:6d}\t{line}")

    message_parts = []
    if len(lines) > 0:
        message_parts.append(
            f"{len(lines)} lines read from file starting from line {line_offset_int}."
        )
    else:
        message_parts.append("No lines read from file.")

    if max_lines_reached:
        message_parts.append(f" Max {_MAX_LINES} lines reached.")
    elif max_bytes_reached:
        message_parts.append(f" Max {_MAX_BYTES} bytes reached.")
    elif len(lines) < n_lines_int:
        message_parts.append(" End of file reached.")

    if truncated_line_numbers:
        message_parts.append(f" Lines {truncated_line_numbers} were truncated.")

    summary = "".join(message_parts).strip()
    if lines_with_no:
        return f"{summary}\n" + "\n".join(lines_with_no)
    return summary


async def write_file(
    path: str,
    content: str,
    *,
    mode: str = "overwrite",
) -> str:
    """Write text content to a file inside the workspace.

    Implementation follows kimi-cli's WriteFile tool.
    """
    if mode not in ("overwrite", "append"):
        raise ToolError(
            f"Invalid write mode: `{mode}`. Mode must be either `overwrite` or `append`."
        )

    if not path:
        raise ToolError("File path cannot be empty.")

    try:
        p = safe_path(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not p.parent.exists():
        raise ToolError(f"`{path}` parent directory does not exist.")

    lock = _get_file_lock(p)
    try:
        async with lock:
            if mode == "overwrite":
                p.write_text(content, encoding="utf-8")
            else:
                with p.open("a", encoding="utf-8") as f:
                    f.write(content)

            file_size = p.stat().st_size
        action = "overwritten" if mode == "overwrite" else "appended to"
        return f"File successfully {action}. Current size: {file_size} bytes."
    except PermissionError as e:
        raise ToolError(f"no write permission for '{path}'.") from e
    except OSError as e:
        raise ToolError(f"Failed to write to {path}. Error: {e}") from e


@dataclass
class Edit:
    """A single edit operation (replacement)."""

    old: str
    new: str
    replace_all: bool = False


async def edit_file(
    path: str,
    old_str: str | None = None,
    new_str: str | None = None,
    *,
    edit: Edit | list[Edit] | None = None,
) -> str:
    """Replace string(s) in a file inside the workspace.

    Implementation follows kimi-cli's StrReplaceFile tool:
    - Supports single edit via old_str/new_str
    - Supports batch edits via edit parameter
    - Exact match required (unless replace_all=True)
    """
    if not path:
        raise ToolError("File path cannot be empty.")

    try:
        p = safe_path(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not p.exists():
        raise ToolError(f"`{path}` does not exist.")
    if not p.is_file():
        raise ToolError(f"`{path}` is not a file.")

    # Build edit list
    edits: list[Edit]
    if edit is not None:
        edits = [edit] if isinstance(edit, Edit) else list(edit)
    elif old_str is not None and new_str is not None:
        edits = [Edit(old=old_str, new=new_str)]
    else:
        raise ToolError("Must provide either (old_str and new_str) or edit parameter")

    if not edits:
        raise ToolError("No edits specified.")

    lock = _get_file_lock(p)
    try:
        async with lock:
            # Read original content
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except PermissionError as e:
                raise ToolError(f"no read permission for '{path}'.") from e

            original_content = content

            # Apply all edits
            for e in edits:
                if not e.old:
                    raise ToolError("edit.old cannot be empty.")

                if e.replace_all:
                    content = content.replace(e.old, e.new)
                else:
                    count = content.count(e.old)
                    if count == 0:
                        raise ToolError(
                            "No replacements were made. The old string was not found in the file."
                        )
                    if count > 1:
                        raise ToolError(
                            f"old_str found {count} times in file. "
                            "Provide more context to make it unique, or use replace_all=True."
                        )
                    content = content.replace(e.old, e.new, 1)

            # Check if any changes were made
            if content == original_content:
                raise ToolError(
                    "No replacements were made. The old string was not found in the file."
                )

            # Write back
            try:
                p.write_text(content, encoding="utf-8")
            except PermissionError as e:
                raise ToolError(f"no write permission for '{path}'.") from e
    except ToolError:
        raise

    return "File successfully edited."


async def list_directory(path: str = ".") -> str:
    """List files and directories at a path inside the workspace."""
    try:
        d = safe_path(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not d.exists():
        raise ToolError(f"`{path}` does not exist.")
    if not d.is_dir():
        raise ToolError(f"`{path}` is not a directory.")

    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        lines: list[str] = []
        for e in entries:
            entry_type = "DIR" if e.is_dir() else "FILE"
            lines.append(f"{entry_type} {e.name}")
        return "\n".join(lines) if lines else "(empty directory)"
    except PermissionError as e:
        raise ToolError(f"no permission to list '{path}'.") from e


async def glob_files(
    pattern: str,
    directory: str = ".",
    *,
    include_dirs: bool = True,
    limit: int = 1000,
) -> str:
    """Find files matching a glob pattern inside the workspace.

    Follows symlinks via Path.walk().
    """
    try:
        base = safe_path(directory)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not base.exists():
        raise ToolError(f"`{directory}` does not exist.")
    if not base.is_dir():
        raise ToolError(f"`{directory}` is not a directory.")

    try:
        # Use walk-based glob to follow symlinks
        matches: list[Path] = []
        for dirpath, dirnames, filenames in base.walk(follow_symlinks=True):
            # Check directory names against pattern
            for name in dirnames:
                full_path = dirpath / name
                rel_path = full_path.relative_to(base)
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(rel_path), pattern):
                    if include_dirs:
                        matches.append(full_path)
            # Check filenames against pattern
            for name in filenames:
                full_path = dirpath / name
                rel_path = full_path.relative_to(base)
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(rel_path), pattern):
                    matches.append(full_path)

        matches.sort()
    except Exception as e:
        raise ToolError(f"Failed to search for pattern {pattern}. Error: {e}") from e

    if not matches:
        return f"No matches found for pattern `{pattern}`."

    message = f"Found {len(matches)} matches for pattern `{pattern}`."
    if len(matches) > limit:
        matches = matches[:limit]
        message += (
            f" Only the first {limit} matches are returned. "
            "You may want to use a more specific pattern."
        )

    return "\n".join(str(p.relative_to(base)) for p in matches)


async def grep_files(
    pattern: str,
    path: str = ".",
    *,
    file_glob: str | None = None,
    output_mode: str = "content",
    before_context: int | None = None,
    after_context: int | None = None,
    context: int | None = None,
    line_number: bool = True,
    ignore_case: bool = False,
    fixed_string: bool = False,
    multiline: bool = False,
    max_results: int = 200,
) -> str:
    """Search file contents for lines matching a pattern.

    Implementation follows kimi-cli's Grep tool:
    - Uses ripgrep if available
    - Falls back to Python implementation otherwise
    - Supports multiple output modes: content, files_with_matches, count_matches
    """
    # Try ripgrep first if available
    if ripgrepy is not None:
        try:
            return await _grep_with_ripgrep(
                pattern,
                path,
                file_glob,
                output_mode,
                before_context,
                after_context,
                context,
                line_number,
                ignore_case,
                fixed_string,
                multiline,
                max_results,
            )
        except Exception:
            # Fall back to Python implementation on any error
            pass

    # Python fallback implementation
    return await _grep_with_python(
        pattern,
        path,
        file_glob,
        output_mode,
        before_context,
        after_context,
        context,
        line_number,
        ignore_case,
        fixed_string,
        multiline,
        max_results,
    )


async def _grep_with_ripgrep(
    pattern: str,
    path: str,
    file_glob: str | None,
    output_mode: str,
    before_context: int | None,
    after_context: int | None,
    context: int | None,
    line_number: bool,
    ignore_case: bool,
    fixed_string: bool,
    multiline: bool,
    max_results: int,
) -> str:
    """Grep implementation using ripgrep."""
    target = safe_path(path)

    if not target.exists():
        raise ToolError(f"`{path}` does not exist.")

    rg = ripgrepy.Ripgrepy(pattern, str(target))

    # Apply options
    if ignore_case:
        rg = rg.ignore_case()
    if fixed_string:
        rg = rg.fixed_strings()
    if multiline:
        rg = rg.multiline().multiline_dotall()
    if file_glob:
        rg = rg.glob(file_glob)

    # Output mode
    if output_mode == "files_with_matches":
        rg = rg.files_with_matches()
    elif output_mode == "count_matches":
        rg = rg.count_matches()
    elif output_mode == "content":
        if before_context is not None:
            rg = rg.before_context(before_context)
        if after_context is not None:
            rg = rg.after_context(after_context)
        if context is not None:
            rg = rg.context(context)
        if line_number:
            rg = rg.line_number()

    result = rg.run()
    output = result.as_string

    if not output:
        return "No matches found."

    # Apply head limit
    if max_results is not None:
        lines = output.split("\n")
        if len(lines) > max_results:
            lines = lines[:max_results]
            output = "\n".join(lines)
            output += f"\n... (results truncated to {max_results} lines)"

    return output


async def _grep_with_python(
    pattern: str,
    path: str,
    file_glob: str | None,
    output_mode: str,
    before_context: int | None,
    after_context: int | None,
    context: int | None,
    line_number: bool,
    ignore_case: bool,
    fixed_string: bool,
    multiline: bool,
    max_results: int,
) -> str:
    """Grep implementation using pure Python (fallback)."""
    try:
        target = safe_path(path)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not target.exists():
        raise ToolError(f"`{path}` does not exist.")

    # Build regex
    if fixed_string:
        pat = re.escape(pattern)
    else:
        pat = pattern

    flags = re.IGNORECASE if ignore_case else 0
    if multiline:
        flags |= re.DOTALL

    try:
        regex = re.compile(pat, flags)
    except re.error as e:
        raise ToolError(f"Invalid regex pattern: {e}") from e

    # Resolve context windows
    b_ctx = before_context if before_context else (context if context else 0)
    a_ctx = after_context if after_context else (context if context else 0)

    # Collect files to search
    if target.is_file():
        files = [target]
    else:
        all_files = _iter_files_with_symlinks(target)
        files = [p for p in all_files if (not file_glob or fnmatch.fnmatch(p.name, file_glob))]

    results: list[str] = []
    total_matches = 0
    truncated = False

    for file in sorted(files):
        try:
            # Skip binary files
            file_size = file.stat().st_size
            with file.open("rb") as f:
                header = f.read(min(1024, file_size))
            if b"\x00" in header:
                continue

            with file.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except (PermissionError, OSError):
            continue

        # Find matching lines
        match_indices = [i for i, line in enumerate(lines) if regex.search(line)]
        if not match_indices:
            continue

        if output_mode == "files_with_matches":
            results.append(str(file))
            total_matches += 1
            if total_matches >= max_results:
                truncated = True
                break
            continue

        if output_mode == "count_matches":
            results.append(f"{file}:{len(match_indices)}")
            continue

        # Content mode
        if b_ctx == 0 and a_ctx == 0:
            for i in match_indices:
                if line_number:
                    results.append(f"{file}:{i + 1}:{lines[i]}")
                else:
                    results.append(f"{file}:{lines[i]}")
                total_matches += 1
                if total_matches >= max_results:
                    truncated = True
                    break
        else:
            # Merge overlapping context ranges
            ranges: list[list[int]] = []
            for i in match_indices:
                lo = max(0, i - b_ctx)
                hi = min(len(lines) - 1, i + a_ctx)
                if ranges and lo <= ranges[-1][1] + 1:
                    ranges[-1][1] = max(ranges[-1][1], hi)
                else:
                    ranges.append([lo, hi])

            match_set = set(match_indices)
            for lo, hi in ranges:
                for i in range(lo, hi + 1):
                    if line_number:
                        sep = ":" if i in match_set else "-"
                        results.append(f"{file}:{i + 1}{sep}{lines[i]}")
                    else:
                        results.append(f"{file}:{lines[i]}")
                    if i in match_set:
                        total_matches += 1
                results.append("--")
                if total_matches >= max_results:
                    truncated = True
                    break

        if truncated:
            break

    if truncated:
        results.append(f"... (results truncated to {max_results} lines)")

    if not results:
        return "No matches found."

    return "\n".join(results)
