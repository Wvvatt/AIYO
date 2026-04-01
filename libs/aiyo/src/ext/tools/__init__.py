"""Extension tools."""

from aiyo.tools.tool import Tool

from .confluence_tools import confluence_cli
from .confluence_tools import health as confluence_health
from .gerrit_tools import gerrit_cli
from .gerrit_tools import health as gerrit_health
from .jira_tools import health as jira_health
from .jira_tools import jira_cli

EXT_TOOLS: list[Tool] = [
    Tool(jira_cli, concurrent=True),
    Tool(confluence_cli, concurrent=True),
    Tool(gerrit_cli, concurrent=True),
]

# Health check functions for info() display
EXT_TOOL_HEALTH_CHECKS = [
    jira_health,
    confluence_health,
    gerrit_health,
]

__all__ = [
    "EXT_TOOLS",
    "EXT_TOOL_HEALTH_CHECKS",
]
