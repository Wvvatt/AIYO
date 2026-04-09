"""Extension tools middleware for MCP tool summary generation."""

from aiyo.agent.middleware import Middleware, ToolCallStartContext


class ExtToolSummaryMiddleware(Middleware):
    """Middleware that generates summaries for extension MCP tools.

    This middleware handles jira_cli, confluence_cli, and gerrit_cli
    by extracting meaningful identity information from their arguments.
    """

    _MCP_TOOLS = frozenset({"jira_cli", "confluence_cli", "gerrit_cli"})

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        """Generate summary for MCP extension tools."""
        if ctx.tool_name not in self._MCP_TOOLS:
            return

        # Extract identity info from MCP tool args
        raw = ctx.tool_args.get("args") or {}
        if isinstance(raw, str):
            try:
                import json

                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}

        cmd = ctx.tool_args.get("command", "")

        match ctx.tool_name:
            case "jira_cli":
                identity = raw.get("issue_key", "")
            case "confluence_cli":
                identity = raw.get("page_id", "")
            case "gerrit_cli":
                identity = raw.get("change_id", "")
            case _:
                identity = ""

        if identity:
            ctx.summary = f"{cmd} {identity}".strip()
        else:
            ctx.summary = cmd
