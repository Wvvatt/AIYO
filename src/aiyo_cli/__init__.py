"""CLI entry point for AIYO."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from aiyo import __version__
from aiyo.config import settings

from .ui import ShellUI

console = Console()

cli = typer.Typer(
    name="aiyo",
    help="AIYO - AI automation agent",
    add_completion=False,
)


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Debug logging"),
):
    """AIYO - AI automation agent."""
    if ctx.invoked_subcommand is not None:
        return

    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    # Default: interactive shell UI
    try:
        ui = ShellUI()
    except Exception as e:
        console.print(f"[bold red]Failed to start:[/bold red] {e}")
        console.print(
            "\nCheck your configuration in [bold]~/.aiyo/.env[/bold]:\n"
            "  PROVIDER=openai\n"
            "  OPENAI_API_KEY=sk-...\n"
            "  MODEL_NAME=gpt-4o-mini"
        )
        raise typer.Exit(1)
    try:
        asyncio.run(ui.run())
    except KeyboardInterrupt:
        pass


# Register subcommands
from aiyo_cli.cmd_prompt import prompt  # noqa: E402
from aiyo_cli.cmd_repl import repl  # noqa: E402


@cli.command()
def info():
    """Show system information."""
    import platform

    console.print(
        f"[bold]AIYO[/bold] v{__version__}\n"
        f"  Python:   {platform.python_version()}\n"
        f"  Provider: {settings.provider}\n"
        f"  Model:    {settings.model_name}"
    )


cli.command()(prompt)
cli.command()(repl)

if __name__ == "__main__":
    cli()
