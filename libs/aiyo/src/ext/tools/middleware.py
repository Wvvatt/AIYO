"""Extension tools middleware for MCP tool summary generation."""

from typing import Any

from aiyo.agent.middleware import Middleware


class ExtToolSummaryMiddleware(Middleware):
    """Middleware that generates summaries for extension MCP tools.

    This middleware handles jira_cli, confluence_cli, and gerrit_cli
    by extracting meaningful identity information from their arguments.
    """

    _MCP_TOOLS = frozenset({"jira_cli", "confluence_cli", "gerrit_cli"})

    async def on_tool_call_start(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, Any],
        summary: str = "",
    ) -> tuple[str, str, dict[str, Any], str]:
        """Generate summary for MCP extension tools.

        Args:
            tool_name: The name of the tool being called.
            tool_id: Unique identifier for this tool call.
            tool_args: The arguments passed to the tool.
            summary: Existing summary from previous middleware.

        Returns:
            Tuple of (tool_name, tool_id, tool_args, summary).
        """
        if tool_name not in self._MCP_TOOLS:
            return tool_name, tool_id, tool_args, summary

        # Extract identity info from MCP tool args
        raw = tool_args.get("args") or {}
        if isinstance(raw, str):
            try:
                import json

                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}

        cmd = tool_args.get("command", "")

        match tool_name:
            case "jira_cli":
                identity = raw.get("issue_key", "")
            case "confluence_cli":
                identity = raw.get("page_id", "")
            case "gerrit_cli":
                identity = raw.get("change_id", "")
            case _:
                identity = ""

        if identity:
            summary = f"{cmd} {identity}".strip()
        else:
            summary = cmd

        return tool_name, tool_id, tool_args, summary
