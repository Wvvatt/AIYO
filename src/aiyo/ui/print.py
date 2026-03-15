"""Non-interactive print UI."""

from __future__ import annotations

import asyncio
import sys

from aiyo.bridge import AgentBridge
from aiyo.bridge.messages import ErrorMsg, TextChunk, ToolCall, TurnEnd


class PrintUI:
    """Simple non-interactive UI for scripting."""

    def __init__(self, agent: AgentBridge | None = None) -> None:
        self.agent = agent or AgentBridge()
        self.verbose = False

    async def run(self, message: str | None = None) -> int:
        """Run single query and print result.

        Returns:
            Exit code (0 for success, 1 for error)
        """
        if message is None:
            # Read from stdin
            message = sys.stdin.read().strip()

        if not message:
            print("Error: No input provided", file=sys.stderr)
            return 1

        # Run agent
        await self.agent.chat(message)

        # Collect response
        response_text = ""
        tool_calls = []

        async for msg in self.agent.bus.iter():
            if isinstance(msg, TextChunk):
                response_text += msg.content
            elif isinstance(msg, ToolCall):
                tool_calls.append(msg)
                if self.verbose:
                    print(f"[{msg.name}]", file=sys.stderr)
            elif isinstance(msg, ErrorMsg):
                print(f"Error: {msg.error}", file=sys.stderr)
                return 1
            elif isinstance(msg, TurnEnd):
                break

        print(response_text)
        return 0

    @classmethod
    def main(cls, args: list[str] | None = None) -> int:
        """CLI entry point."""
        import argparse

        parser = argparse.ArgumentParser(description="AIYO Print Mode")
        parser.add_argument("prompt", nargs="?", help="Query prompt")
        parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
        args = parser.parse_args(args)

        ui = cls()
        ui.verbose = args.verbose

        try:
            return asyncio.run(ui.run(args.prompt))
        except KeyboardInterrupt:
            return 130
