"""AML (Amlogic) tools."""

from .jira_tools import jira_cli

AML_TOOLS = [jira_cli]

__all__ = ["AML_TOOLS", "jira_cli"]
