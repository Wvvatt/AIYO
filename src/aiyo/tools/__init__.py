"""Built-in tools for the AIYO agent."""

from ._sandbox import safe_path
from .filesystem import (
    glob_files,
    grep_files,
    list_directory,
    read_file,
    str_replace_file,
    write_file,
)
from .misc import get_current_time, think
from .shell import run_shell_command
from .skills import get_skill_descriptions, load_skill
from .todo import todo
from .web import fetch_url

# Read-only tools (safe operations that don't modify state)
READ_TOOLS = [
    get_current_time,
    think,
    read_file,
    list_directory,
    glob_files,
    grep_files,
    fetch_url,
    todo,
    load_skill,
]

# Write tools (operations that modify files or execute commands)
WRITE_TOOLS = [
    write_file,
    str_replace_file,
    run_shell_command,
]

# Default: all tools combined
DEFAULT_TOOLS = READ_TOOLS + WRITE_TOOLS

__all__ = [
    "DEFAULT_TOOLS",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "safe_path",
    "get_current_time",
    "think",
    "read_file",
    "write_file",
    "str_replace_file",
    "list_directory",
    "glob_files",
    "grep_files",
    "run_shell_command",
    "fetch_url",
    "todo",
    "load_skill",
    "get_skill_descriptions",
]
