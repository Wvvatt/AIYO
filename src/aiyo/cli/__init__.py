"""CLI entry point for AIYO."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console

from aiyo.bridge import AgentBridge
from aiyo.config import settings
from aiyo.ui import PrintUI, ShellUI

console = Console()

cli = typer.Typer(
    name="aiyo",
    help="AIYO - AI automation agent for Amlogic R&D",
    add_completion=False,
)


@cli.callback(invoke_without_command=True)
def ui(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit", is_eager=True
    ),
    prompt: str | None = typer.Option(
        None, "--prompt", "-p", help="Run single prompt (non-interactive)"
    ),
    work_dir: Path | None = typer.Option(
        None, "--work-dir", "-w", exists=True, file_okay=False, help="Working directory"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    debug: bool = typer.Option(False, "--debug", help="Debug logging"),
):
    """AIYO - AI automation agent."""
    if version:
        console.print("AIYO version 0.1.0")
        raise typer.Exit()

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

    # Create agent
    agent = AgentBridge()

    # Run mode
    if prompt or not sys.stdin.isatty():
        # Non-interactive mode
        ui = PrintUI(agent)
        ui.verbose = verbose
        code = asyncio.run(ui.run(prompt))
        raise typer.Exit(code)
    else:
        # Interactive mode
        ui = ShellUI(agent, model_name=settings.model_name)
        try:
            asyncio.run(ui.run())
        except KeyboardInterrupt:
            pass


@cli.command()
def repl():
    """Start simple REPL (no prompt-toolkit, no Rich)."""
    import sys

    from aiyo.session import Session
    from aiyo.session.middleware_base import Middleware
    from aiyo.tools import DEFAULT_TOOLS

    class ToolDisplayMiddleware(Middleware):
        """Print tool calls to stdout in the REPL."""

        def _format_name(self, name: str) -> str:
            return "".join(p.capitalize() for p in name.split("_"))

        def after_tool_call(self, tool_name: str, tool_args: dict, result: object) -> object:
            display = self._format_name(tool_name)
            match tool_name:
                case "todo":
                    print(f"\033[36m{display}\033[0m\n{result}")
                case "think":
                    print(f"\033[36m{display}\033[0m\n{tool_args.get('thought', '')}")
                case "read_file" | "write_file" | "str_replace_file":
                    print(f"\033[36m{display}\033[0m {tool_args.get('path', '')}")
                case "glob_files":
                    print(f"\033[36m{display}\033[0m {tool_args.get('pattern', '')}")
                case "list_directory":
                    print(f"\033[36m{display}\033[0m {tool_args.get('relative_path', '.')}")
                case "run_shell_command":
                    cmd = tool_args.get("command", "")
                    print(f"\033[36m{display}\033[0m {cmd[:80]}")
                case _:
                    print(f"\033[36m{display}\033[0m")
            return result

    agent = Session(tools=DEFAULT_TOOLS, extra_middleware=[ToolDisplayMiddleware()])
    print(f"AIYO REPL  ({settings.model_name})  Ctrl-C/Ctrl-D to exit\n")

    while True:
        try:
            user_input = input("\033[34maiyo >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            sys.exit(0)

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            print("Bye.")
            break
        if user_input == "/reset":
            agent.reset()
            print("Session reset.")
            continue
        if user_input == "/stats":
            print(agent.print_stats())
            continue
        if user_input in ("/help", "/h"):
            print("Commands: /reset /stats /exit /help")
            continue

        response = agent.chat(user_input)
        print(f"{response}\n")


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


if __name__ == "__main__":
    cli()
