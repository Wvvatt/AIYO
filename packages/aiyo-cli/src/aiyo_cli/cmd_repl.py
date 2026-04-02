"""Simple REPL command (no prompt-toolkit, no Rich)."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiyo.agent.middleware import Middleware

try:
    from ext.tools import EXT_TOOL_MIDDLEWARE, EXT_TOOLS
except ImportError:
    EXT_TOOLS = []
    EXT_TOOL_MIDDLEWARE = []

logger = logging.getLogger("aiyo.cli.repl")

BLUE = "\033[34m"
CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"


class REPLDisplayMiddleware(Middleware):
    """Print tool calls to stdout in the REPL."""

    async def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict,
        tool_error: Exception | None,
        result: object,
    ) -> object:
        display = "".join(p.capitalize() for p in tool_name.split("_"))
        match tool_name:
            case "think":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('thought', '')}{RESET}")
            case "read_file" | "write_file" | "edit_file":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('path', '')}{RESET}")
            case "read_image" | "read_pdf":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('path', '')}{RESET}")
            case "glob_files":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('pattern', '')}{RESET}")
            case "list_directory":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('path', '.')}{RESET}")
            case "task_create" | "task_update" | "task_delete":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('task_id', '')}{RESET}")
            case "shell":
                cmd = tool_args.get("command", "")
                print(f"{CYAN}{display}{RESET} {GRAY}{cmd[:80]}{RESET}")
            case "load_skill":
                print(f"{CYAN}{display}{RESET} {GRAY}{tool_args.get('name', '')}{RESET}")
            case _:
                print(f"{CYAN}{display}{RESET}")
        return result


def _print_help() -> None:
    print("Commands:")
    print("  /reset         - Reset session (clear history, keep system prompt)")
    print("  /stats         - Show detailed session statistics")
    print("  /compact       - Compress conversation history (two-layer)")
    print("  /summary       - Show history summary (token usage)")
    print("  /save          - Save history to .history/history_YYYYMMDD_HHMMSS.jsonl")
    print("  /exit, /quit   - Exit REPL")
    print("  /help, /h      - Show this help")


async def _handle_command(agent, user_input: str) -> bool:
    """Handle slash command. Return True when handled."""
    if user_input in ("/exit", "/quit"):
        print("Bye.")
        raise EOFError
    if user_input == "/reset":
        agent.reset()
        print("Session reset.")
        return True
    if user_input == "/stats":
        print(agent.print_stats())
        return True
    if user_input == "/compact":
        result = await agent.compact()
        print(result)
        return True
    if user_input == "/summary":
        summary = agent.get_history_summary()
        print(f"Messages: {summary.get('message_count', 0)}")
        print(f"Tokens: {summary.get('token_count', 0)} / {summary.get('token_limit', 0)}")
        print(f"Usage: {summary.get('token_usage_percent', 0):.1f}%")
        if "role_counts" in summary:
            print("Role counts:", summary["role_counts"])
        return True
    if user_input == "/save":
        path = agent.save_history()
        print(f"History saved to {path}")
        return True
    if user_input in ("/help", "/h"):
        _print_help()
        return True
    return False


async def _chat_loop(agent) -> None:
    """Interactive chat loop."""
    while True:
        try:
            user_input = input(f"{BLUE}aiyo >> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue

        try:
            if user_input.startswith("/"):
                if await _handle_command(agent, user_input):
                    continue

            response = await agent.chat(user_input)
            print(f"{response}\n")
        except EOFError:
            return
        except KeyboardInterrupt:
            print("\nCancelled.\n")
        except Exception as exc:
            logger.exception("REPL command failed")
            print(f"Error: {exc}\n", file=sys.stderr)


def repl() -> None:
    """Start simple REPL (no prompt-toolkit, no Rich)."""
    from aiyo import Agent

    agent = Agent(
        extra_tools=EXT_TOOLS,
        extra_middleware=list(EXT_TOOL_MIDDLEWARE) + [REPLDisplayMiddleware()],
    )
    print(f"AIYO REPL  ({agent.model_name})  Ctrl-C/Ctrl-D to exit\n")
    asyncio.run(_chat_loop(agent))
