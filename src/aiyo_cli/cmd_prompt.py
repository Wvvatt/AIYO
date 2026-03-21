"""Single-prompt command."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Annotated

import typer

from aiyo.tools import WRITE_TOOLS

from .ui.theme import console

logger = logging.getLogger("aiyo.cli.prompt")


def _resolve_prompt_text(text: str | None) -> str:
    """Resolve prompt text from argument or stdin."""
    if text:
        resolved = text.strip()
        if resolved:
            return resolved

    if sys.stdin.isatty():
        console.print("[error]Error: provide a prompt or pipe stdin[/error]")
        raise typer.Exit(1)

    resolved = sys.stdin.read().strip()
    if not resolved:
        console.print("[error]Error: no input provided[/error]")
        raise typer.Exit(1)
    return resolved


async def _run_single_prompt(text: str) -> None:
    """Execute one prompt turn and print only model response."""
    from aiyo.agent.agent import Agent

    agent = Agent(extra_tools=WRITE_TOOLS)
    response = await agent.chat(text)
    print(response)


def prompt(
    text: Annotated[str | None, typer.Argument(help="Prompt text")] = None,
) -> None:
    """Run a single prompt and print response only (script-friendly)."""
    resolved_text = _resolve_prompt_text(text)
    logger.debug("Running single prompt (%d chars)", len(resolved_text))

    try:
        asyncio.run(_run_single_prompt(resolved_text))
    except KeyboardInterrupt:
        logger.info("Prompt interrupted by user")
        raise typer.Exit(130)
    except asyncio.CancelledError:
        logger.info("Prompt cancelled")
        raise typer.Exit(130)
    except Exception as exc:
        logger.exception("Prompt command failed")
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(1)
