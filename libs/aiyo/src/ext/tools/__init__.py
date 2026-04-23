"""Extension tools."""

from .analyze_mode_tools import (
    enter_analyze,
    exit_analyze,
    read_artifacts,
    write_artifact,
)
from .confluence_tools import confluence_cli
from .gerrit_tools import gerrit_cli
from .jira_tools import jira_cli
from .opengrok_tools import opengrok_cli

EXT_TOOLS = [
    jira_cli,
    confluence_cli,
    gerrit_cli,
    opengrok_cli,
    enter_analyze,
    write_artifact,
    read_artifacts,
    exit_analyze,
]

__all__ = [
    "EXT_TOOLS",
    "enter_analyze",
    "write_artifact",
    "read_artifacts",
    "exit_analyze",
    "opengrok_cli",
]
