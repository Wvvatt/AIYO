"""Built-in tools for the AIYO agent."""

from .tool_meta import (
    ToolHealthFn,
    ToolMeta,
    ToolSummaryFn,
    get_summary,
    get_tool_meta,
    health_check,
    is_gatherable,
    is_not_for_planmode,
    tool,
)
from ._sandbox import safe_path
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
from .interactive import Option, Question, ask_user
from .misc import get_current_time, think
from .pdf import read_pdf
from .shell import shell
from .skills import load_skill, load_skill_resource
from .todo import todo_set
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
    "safe_path",
    "ToolError",
    "ToolMeta",
    "ToolSummaryFn",
    "ToolHealthFn",
    "tool",
    "get_tool_meta",
    "get_summary",
    "health_check",
    "is_gatherable",
    "is_not_for_planmode",
    "get_current_time",
    "think",
    "read_file",
    "read_image",
    "read_pdf",
    "write_file",
    "edit_file",
    "list_directory",
    "glob_files",
    "grep_files",
    "shell",
    "fetch_url",
    "todo_set",
    "load_skill",
    "load_skill_resource",
    "ask_user",
    "Option",
    "Question",
]
