"""Built-in tools for the AIYO agent."""

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
from .tasks import task_create, task_delete, task_get, task_list, task_update
from .web import fetch_url

# Read-only tools (safe operations that don't modify state)
READ_TOOLS = [
    get_current_time,
    think,
    read_file,
    read_image,
    read_pdf,
    list_directory,
    glob_files,
    grep_files,
    fetch_url,
    task_create,
    task_get,
    task_update,
    task_list,
    task_delete,
    load_skill,
    load_skill_resource,
    ask_user,
]

# Write tools (operations that modify files or execute commands)
WRITE_TOOLS = [
    write_file,
    edit_file,
    shell,
]

__all__ = [
    "WRITE_TOOLS",
    "READ_TOOLS",
    "safe_path",
    "ToolError",
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
    "task_create",
    "task_get",
    "task_update",
    "task_list",
    "task_delete",
    "load_skill",
    "load_skill_resource",
    "ask_user",
    "Option",
    "Question",
]
