"""AML (Amlogic) tools."""

from .confluence_tools import confluence_cli
from .gerrit_tools import gerrit_cli
from .jira_tools import jira_cli

AML_TOOLS = [jira_cli, confluence_cli, gerrit_cli]

__all__ = ["AML_TOOLS", "confluence_cli", "gerrit_cli", "jira_cli"]
