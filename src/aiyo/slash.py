"""Slash command handlers for the interactive CLI."""

import json
from datetime import datetime
from pathlib import Path

from .session import Session

_HISTORY_DIR = Path(".history")

HELP = """\
Slash commands:
  /stats        Print token usage and timing statistics
  /clear        Clear conversation history
  /history      Show conversation history summary
  /save         Save conversation history to .history/
  /compact      Two-layer compression: shrink tool results, then LLM-summarize
  /debug        Toggle debug logging
  /help         Show this help message
"""


def _save_history(agent: Session) -> None:
    _HISTORY_DIR.mkdir(exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    path = _HISTORY_DIR / filename
    history = agent.get_history()
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"History saved to {path}  ({len(history)} messages)")


def handle(cmd: str, agent: Session, debug: list[bool]) -> None:
    """Dispatch a slash command."""
    match cmd:
        case "/stats":
            print(agent.print_stats())
        case "/clear":
            agent.reset()
            print("Conversation history cleared.")
        case "/history":
            summary = agent.get_history_summary()
            for k, v in summary.items():
                print(f"  {k}: {v}")
        case "/save":
            _save_history(agent)
        case "/compact":
            print(agent.compact(transcript_dir=_HISTORY_DIR))
        case "/debug":
            debug[0] = not debug[0]
            agent.set_debug(debug[0])
            print(f"Debug logging {'enabled' if debug[0] else 'disabled'}.")
        case "/help":
            print(HELP)
        case _:
            print(f"Unknown command: {cmd}  (type /help for available commands)")
