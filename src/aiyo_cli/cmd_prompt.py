"""Single-prompt command."""

from __future__ import annotations

import asyncio
import sys

import typer
from aiyo.tools import WRITE_TOOLS

from .ui.theme import console


def prompt(
    text: str = typer.Argument(None, help="Prompt text"),
):
    """Run a single prompt, print content only (no tool logs)."""
    from aiyo import Agent

    if not text and sys.stdin.isatty():
        console.print("[error]Error: provide a prompt or pipe stdin[/error]")
        raise typer.Exit(1)

    if not text:
        text = sys.stdin.read().strip()
    if not text:
        console.print("[error]Error: no input provided[/error]")
        raise typer.Exit(1)

    async def run():
        try:
            response = await Agent(extra_tools=WRITE_TOOLS).chat(text)
            print(response)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1)

    asyncio.run(run())
