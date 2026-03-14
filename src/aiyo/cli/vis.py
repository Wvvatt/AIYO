"""Vis command stub for agent tracing visualization.

This is a placeholder for future visualization support.
"""

from __future__ import annotations

from typing import Annotated

import typer

cli = typer.Typer(help="Agent tracing visualizer (placeholder).")


@cli.callback(invoke_without_command=True)
def vis(
    ctx: typer.Context,
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind to")] = 5495,
):
    """Launch the agent tracing visualizer (not yet implemented)."""
    typer.echo("Visualization is not yet implemented in AIYO.")
    raise typer.Exit(1)
