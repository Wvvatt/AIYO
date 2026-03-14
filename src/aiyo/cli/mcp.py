"""MCP (Model Context Protocol) support stub.

This is a placeholder for future MCP support.
"""

from __future__ import annotations

from typing import Annotated

import typer

cli = typer.Typer(help="MCP server management (placeholder).")


@cli.callback(invoke_without_command=True)
def mcp(
    ctx: typer.Context,
):
    """MCP server management (not yet implemented)."""
    typer.echo("MCP support is not yet implemented in AIYO.")
    raise typer.Exit(1)
