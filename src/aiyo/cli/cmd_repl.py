"""Simple REPL command (no prompt-toolkit, no Rich)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from aiyo.config import settings
from aiyo.session.middleware_base import Middleware


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


def repl():
    """Start simple REPL (no prompt-toolkit, no Rich)."""
    from aiyo.session import Session
    from aiyo.tools import DEFAULT_TOOLS

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
        if user_input == "/compact":
            result = agent.compact()
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
        if user_input == "/debug":
            agent.set_debug(True)
            print("Debug mode enabled.")
            continue
        if user_input == "/nodebug":
            agent.set_debug(False)
            print("Debug mode disabled.")
            continue
        if user_input == "/save":
            history_dir = Path(".history")
            history_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = history_dir / f"history_{timestamp}.jsonl"

            history = agent.get_history()
            with open(save_path, "w", encoding="utf-8") as f:
                for msg in history:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")

            print(f"History saved to {save_path} ({len(history)} messages)")
            continue
        if user_input in ("/help", "/h"):
            print("Commands:")
            print("  /reset     - Reset session (clear history, keep system prompt)")
            print("  /stats     - Show detailed session statistics")
            print("  /compact   - Compress conversation history (two-layer)")
            print("  /summary   - Show history summary (token usage)")
            print("  /save      - Save history to .history/history_YYYYMMDD_HHMMSS.jsonl")
            print("  /debug     - Enable debug logging")
            print("  /nodebug   - Disable debug logging")
            print("  /exit, /quit  - Exit REPL")
            print("  /help, /h     - Show this help")
            continue

        response = agent.chat(user_input)
        print(f"{response}\n")
