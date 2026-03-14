"""Info command for AIYO."""

from __future__ import annotations

import platform
from typing import Annotated

import typer

cli = typer.Typer(help="Show version and information.")


@cli.callback(invoke_without_command=True)
def info(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output information as JSON."),
    ] = False,
):
    """Show version and system information."""
    import json
    
    from aiyo.config import settings
    
    info_data = {
        "version": "0.1.0",
        "python_version": platform.python_version(),
        "provider": settings.provider,
        "model": settings.model_name,
    }
    
    if json_output:
        typer.echo(json.dumps(info_data, indent=2))
    else:
        typer.echo(f"AIYO version: {info_data['version']}")
        typer.echo(f"Python version: {info_data['python_version']}")
        typer.echo(f"Provider: {info_data['provider']}")
        typer.echo(f"Model: {info_data['model']}")
