"""Built-in tools for the AIYO agent."""

from .exceptions import ToolError
from .filesystem import (
    edit_file,
    glob_files,
    grep_files,
    list_directory,
    read_file,
    write_file,
)
from .image import read_image
from .interactive import ask_user
from .misc import get_current_time, think
from .pdf import read_pdf
from .shell import shell
from .skills import load_skill, load_skill_resource
from .todo import todo_set
from .tool_meta import (
    get_summary,
    health_check,
    is_gatherable,
    is_not_for_planmode,
    tool,
)
from .web import fetch_url

BUILTIN_TOOLS = [
    get_current_time,
    think,
    read_file,
    read_image,
    read_pdf,
    list_directory,
    glob_files,
    grep_files,
    fetch_url,
    todo_set,
    load_skill,
    load_skill_resource,
    ask_user,
    write_file,
    edit_file,
    shell,
]

__all__ = [
    "BUILTIN_TOOLS",
    "ToolError",
    "tool",
    "get_summary",
    "health_check",
    "is_gatherable",
    "is_not_for_planmode",
]
