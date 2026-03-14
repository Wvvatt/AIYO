"""Export command for session data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

cli = typer.Typer(help="Export session data.")


@cli.callback(invoke_without_command=True)
def export(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path. Default: aiyo-session-{timestamp}.json",
        ),
    ] = None,
):
    """Export current session to a file.
    
    This command exports the conversation history from the current
    working directory's .history folder.
    """
    from datetime import datetime
    
    history_dir = Path(".history")
    if not history_dir.exists():
        typer.echo("No history directory found.", err=True)
        raise typer.Exit(1)
    
    # Find the most recent history file
    history_files = sorted(history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not history_files:
        typer.echo("No history files found.", err=True)
        raise typer.Exit(1)
    
    latest = history_files[-1]
    
    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path(f"aiyo-session-{timestamp}.json")
    
    # Copy the file
    import shutil
    shutil.copy2(latest, output)
    typer.echo(f"Exported to {output}")
