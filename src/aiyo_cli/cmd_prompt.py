"""Single-prompt command."""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console

from aiyo.tools import DEFAULT_TOOLS

console = Console()


def prompt(
    text: str = typer.Argument(None, help="Prompt text"),
):
    """Run a single prompt, print content only (no tool logs)."""
    from aiyo import Agent

    if not text and sys.stdin.isatty():
        console.print("[red]Error: provide a prompt or pipe stdin[/red]")
        raise typer.Exit(1)

    if not text:
        text = sys.stdin.read().strip()
    if not text:
        console.print("[red]Error: no input provided[/red]")
        raise typer.Exit(1)

    async def run():
        try:
            response = await Agent(DEFAULT_TOOLS).chat(text)
            print(response)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1)

    asyncio.run(run())
