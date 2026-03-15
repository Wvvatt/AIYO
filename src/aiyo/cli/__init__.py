"""CLI entry point for AIYO."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from aiyo.config import settings
from aiyo.session import Session
from aiyo.ui import ShellUI

console = Console()

cli = typer.Typer(
    name="aiyo",
    help="AIYO - AI automation agent for Amlogic R&D",
    add_completion=False,
)


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    work_dir: Path | None = typer.Option(
        None, "--work-dir", "-w", exists=True, file_okay=False, help="Working directory"
    ),
    debug: bool = typer.Option(False, "--debug", help="Debug logging"),
):
    """AIYO - AI automation agent."""
    if ctx.invoked_subcommand is not None:
        return

    # Setup
    if work_dir:
        import os

        os.chdir(work_dir)
        settings.work_dir = work_dir

    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    # Default: interactive shell UI
    session = Session()
    ui = ShellUI(session)
    try:
        asyncio.run(ui.run())
    except KeyboardInterrupt:
        pass


# Register subcommands
from aiyo.cli.cmd_prompt import prompt  # noqa: E402
from aiyo.cli.cmd_repl import repl  # noqa: E402


@cli.command()
def info():
    """Show system information."""
    import platform

    console.print(
        f"[bold]AIYO[/bold] v0.1.0\n"
        f"  Python:   {platform.python_version()}\n"
        f"  Provider: {settings.provider}\n"
        f"  Model:    {settings.model_name}"
    )


cli.command()(prompt)
cli.command()(repl)

if __name__ == "__main__":
    cli()
