"""Web UI command stub.

This is a placeholder for future web UI support.
"""

from __future__ import annotations

from typing import Annotated

import typer

cli = typer.Typer(help="Web interface (placeholder).")


@cli.callback(invoke_without_command=True)
def web(
    ctx: typer.Context,
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind to")] = 5494,
):
    """Run AIYO web interface (not yet implemented)."""
    typer.echo("Web UI is not yet implemented in AIYO.")
    raise typer.Exit(1)
