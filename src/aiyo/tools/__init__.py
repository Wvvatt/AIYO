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
from .todo import todo
from .web import fetch_url

DEFAULT_TOOLS = [
    get_current_time,
    think,
    read_file,
    write_file,
    str_replace_file,
    list_directory,
    glob_files,
    grep_files,
    run_shell_command,
    fetch_url,
    todo,
]

__all__ = [
    "DEFAULT_TOOLS",
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
]
