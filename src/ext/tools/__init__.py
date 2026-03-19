"""Extension tools."""

from .confluence_tools import confluence_cli
from .confluence_tools import health as confluence_health
from .gerrit_tools import gerrit_cli
from .gerrit_tools import health as gerrit_health
from .jira_tools import health as jira_health
from .jira_tools import jira_cli

EXT_TOOLS = [jira_cli, confluence_cli, gerrit_cli]

# Health check functions for info() display
EXT_TOOL_HEALTH_CHECKS = [
    jira_health,
    confluence_health,
    gerrit_health,
]

__all__ = [
    "EXT_TOOLS",
    "EXT_TOOL_HEALTH_CHECKS",
    "confluence_cli",
    "confluence_health",
    "gerrit_cli",
    "gerrit_health",
    "jira_cli",
    "jira_health",
]
