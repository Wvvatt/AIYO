"""Simple REPL command (no prompt-toolkit, no Rich)."""

from __future__ import annotations

import asyncio
import sys

from aiyo import Middleware

try:
    from ext.tools import EXT_TOOLS
except ImportError:
    EXT_TOOLS = []


class ToolDisplayMiddleware(Middleware):
    """Print tool calls to stdout in the REPL."""

    def _format_name(self, name: str) -> str:
        return "".join(p.capitalize() for p in name.split("_"))

    def on_tool_call_end(self, tool_name: str, tool_args: dict, result: object) -> object:
        display = self._format_name(tool_name)
        match tool_name:
            case "todo":
                print(f"\033[36m{display}\033[0m\n\033[90m{result}\033[0m")
            case "think":
                print(f"\033[36m{display}\033[0m \033[90m{tool_args.get('thought', '')}\033[0m")
            case "read_file" | "write_file" | "str_replace_file":
                print(f"\033[36m{display}\033[0m \033[90m{tool_args.get('path', '')}\033[0m")
            case "glob_files":
                print(f"\033[36m{display}\033[0m \033[90m{tool_args.get('pattern', '')}\033[0m")
            case "list_directory":
                print(
                    f"\033[36m{display}\033[0m \033[90m{tool_args.get('relative_path', '.')}\033[0m"
                )
            case "shell":
                cmd = tool_args.get("command", "")
                print(f"\033[36m{display}\033[0m \033[90m{cmd[:80]}\033[0m")
            case "load_skill":
                print(f"\033[36m{display}\033[0m \033[90m{tool_args.get('name', '')}\033[0m")
            case _:
                print(f"\033[36m{display}\033[0m")
        return result


def repl():
    """Start simple REPL (no prompt-toolkit, no Rich)."""
    from aiyo import Agent
    from aiyo.tools import WRITE_TOOLS

    agent = Agent(extra_tools=WRITE_TOOLS + EXT_TOOLS, extra_middleware=[ToolDisplayMiddleware()])
    print(f"AIYO REPL  ({agent.model_name})  Ctrl-C/Ctrl-D to exit\n")

    async def chat_loop():
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
            if user_input == "/compact":
                result = await agent.compact()
                print(result)
                continue
            if user_input == "/summary":
                summary = agent.get_history_summary()
                print(f"Messages: {summary.get('message_count', 0)}")
                print(f"Tokens: {summary.get('token_count', 0)} / {summary.get('token_limit', 0)}")
                print(f"Usage: {summary.get('token_usage_percent', 0):.1f}%")
                if "role_counts" in summary:
                    print("Role counts:", summary["role_counts"])
                continue
            if user_input == "/save":
                path = agent.save_history()
                print(f"History saved to {path}")
                continue
            if user_input in ("/help", "/h"):
                print("Commands:")
                print("  /reset     - Reset session (clear history, keep system prompt)")
                print("  /stats     - Show detailed session statistics")
                print("  /compact   - Compress conversation history (two-layer)")
                print("  /summary   - Show history summary (token usage)")
                print("  /save      - Save history to .history/history_YYYYMMDD_HHMMSS.jsonl")
                print("  /exit, /quit  - Exit REPL")
                print("  /help, /h     - Show this help")
                continue

            response = await agent.chat(user_input)
            print(f"{response}\n")

    asyncio.run(chat_loop())
