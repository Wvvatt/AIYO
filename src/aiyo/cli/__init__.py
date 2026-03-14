"""CLI module for AIYO agent."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

cli = typer.Typer(
    help="AIYO - AI automation agent for Amlogic R&D",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

UIMode = Literal["shell", "print"]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo("AIYO version 0.1.0")
        raise typer.Exit()


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Print verbose information."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging."),
    ] = False,
    work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir",
            "-w",
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Working directory for the agent.",
        ),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            "-p",
            help="User prompt (non-interactive mode).",
        ),
    ] = None,
    print_mode: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Run in print mode (non-interactive).",
        ),
    ] = False,
):
    """AIYO - AI automation agent for Amlogic R&D."""
    import logging
    
    from aiyo.config import settings
    from aiyo.bridge import AiyoSoul
    from aiyo.ui.shell import Shell
    
    if ctx.invoked_subcommand is not None:
        return
    
    # Configure logging
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    elif verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)
    
    # Change work dir if specified
    if work_dir:
        import os
        os.chdir(work_dir)
        settings.work_dir = work_dir
    
    # Create soul
    soul = AiyoSoul(model_name=settings.model_name, work_dir=settings.work_dir)
    
    if debug:
        soul.set_debug(True)
    
    if print_mode or prompt:
        # Non-interactive mode
        if not prompt:
            # Read from stdin
            if not sys.stdin.isatty():
                prompt = sys.stdin.read().strip()
        
        if not prompt:
            typer.echo("Error: No prompt provided. Use --prompt or pipe input.", err=True)
            raise typer.Exit(1)
        
        # Run the prompt
        async def _run_once():
            response = await soul.chat(prompt)
            typer.echo(response)
        
        asyncio.run(_run_once())
    else:
        # Interactive shell mode
        async def _run_shell():
            shell = Shell(soul)
            await shell.run()
        
        try:
            asyncio.run(_run_shell())
        except KeyboardInterrupt:
            pass


@cli.command()
def repl():
    """Start the simple REPL (legacy mode)."""
    from aiyo.repl import main
    main()


# Import subcommands
from .info import cli as info_cli
from .export import cli as export_cli

cli.add_typer(info_cli, name="info")
cli.add_typer(export_cli, name="export")
