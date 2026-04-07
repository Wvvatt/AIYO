"""CLI entry point for AIYO."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

import typer
from aiyo import __version__
from aiyo.config import settings
from aiyo.tools import BUILTIN_TOOLS
from rich.console import Console

from .cmd_prompt import prompt
from .cmd_repl import repl
from .ui import ShellUI

console = Console()
logger = logging.getLogger("aiyo.cli")
_THIRD_PARTY_LOGGERS = (
    "openai",
    "anthropic",
    "any_llm",
    "gateway",
    "httpx",
    "httpcore",
    "markdown_it",
    "PIL",
)

cli = typer.Typer(
    name="aiyo",
    help="AIYO - AI automation agent",
    add_completion=True,
)


def _configure_logging(debug: bool) -> None:
    """Configure root and package loggers with clear levels."""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )

    logging.getLogger("aiyo").setLevel(logging.DEBUG if debug else logging.WARNING)
    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _start_shell_ui() -> None:
    """Start default interactive shell."""
    try:
        ui = ShellUI()
    except Exception as exc:
        console.print(f"[bold red]Failed to start:[/bold red] {exc}")
        console.print(
            "\nCheck your configuration in [bold]~/.aiyo/.env[/bold]:\n"
            "  PROVIDER=openai\n"
            "  OPENAI_API_KEY=sk-...\n"
            "  MODEL_NAME=gpt-4o-mini"
        )
        raise typer.Exit(1) from exc

    try:
        asyncio.run(ui.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


def _load_ext_tools() -> tuple[list[Any], list[Any]]:
    """Load extension tools and optional health checks."""
    try:
        from ext.tools import EXT_TOOL_HEALTH_CHECKS, EXT_TOOLS
    except ImportError:
        return [], []
    return list(EXT_TOOLS), list(EXT_TOOL_HEALTH_CHECKS)


def _collect_ext_health(health_checks: list[Any]) -> dict[str, dict[str, Any]]:
    """Run extension health checks and return name->result map."""
    health: dict[str, dict[str, Any]] = {}
    for health_func in health_checks:
        try:
            result = health_func()
            health[result["name"]] = result
            logger.debug("Ext tool health: %s => %s", result["name"], result["status"])
        except Exception:
            logger.exception("Ext tool health check failed: %s", health_func.__name__)
    return health


@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Debug logging"),
) -> None:
    """AIYO - AI automation agent."""
    _configure_logging(debug)
    logger.debug("CLI started (subcommand=%s, debug=%s)", ctx.invoked_subcommand, debug)
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["debug"] = debug

    if ctx.invoked_subcommand is None:
        # Keep interactive UI clean unless debug is explicitly enabled.
        if not debug:
            logging.getLogger("aiyo").setLevel(logging.WARNING)
        _start_shell_ui()


@cli.command()
def info() -> None:
    """Show system information."""
    ext_tools, ext_health_checks = _load_ext_tools()
    ext_health = _collect_ext_health(ext_health_checks)
    all_tools = BUILTIN_TOOLS + ext_tools

    console.print(
        f"[bold]AIYO[/bold] v{__version__}\n"
        f"  Python:   {platform.python_version()}\n"
        f"  Provider: {settings.provider}\n"
        f"  Model:    {settings.model_name}\n"
        f"  Tools:    {len(all_tools)}"
    )
    console.print("\n[bold]Available tools:[/bold]")

    for tool in all_tools:
        tool_name = tool.__name__
        if tool_name in ext_health:
            health = ext_health[tool_name]
            status = health["status"]
            message = health["message"]
            if status == "ok":
                console.print(f"  • {tool_name:18} [green]● connected[/green]    {message}")
            elif status == "not_configured":
                console.print(f"  • {tool_name:18} [dim]○ not configured[/dim]  {message}")
            else:  # error
                console.print(f"  • {tool_name:18} [red]● error[/red]          {message}")
        else:
            console.print(f"  • {tool_name}")


cli.command(name="prompt")(prompt)
cli.command(name="repl")(repl)

if __name__ == "__main__":
    cli()
