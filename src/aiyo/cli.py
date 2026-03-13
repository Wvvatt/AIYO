"""Simple CLI entry point for interactive agent chat."""

import logging
import sys

from . import slash
from .agent import Agent
from .tools import DEFAULT_TOOLS


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    agent = Agent(tools=DEFAULT_TOOLS)
    debug = [False]
    print("AIYO Agent  (Ctrl-C or Ctrl-D to exit  |  /help for commands)\n")

    while True:
        try:
            user_input = input("\033[34maiyo >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.startswith("/"):
            slash.handle(user_input, agent, debug)
            continue

        response = agent.chat(user_input)
        print(f"Agent: {response}\n")


if __name__ == "__main__":
    main()
