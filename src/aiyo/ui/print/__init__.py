"""Print UI module for non-interactive output."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Literal

from aiyo.bridge import AiyoSoul

InputFormat = Literal["text", "stream-json"]
OutputFormat = Literal["text", "stream-json"]


class PrintUI:
    """Non-interactive print UI."""
    
    def __init__(
        self,
        soul: AiyoSoul,
        input_format: InputFormat,
        output_format: OutputFormat,
        final_only: bool = False,
    ):
        self.soul = soul
        self.input_format = input_format
        self.output_format = output_format
        self.final_only = final_only
    
    async def run(self, command: str | None = None) -> bool:
        """Run the print UI."""
        if command is None:
            if not sys.stdin.isatty() and self.input_format == "text":
                command = sys.stdin.read().strip()
        
        if not command:
            if self.input_format == "text":
                return True
            else:
                # TODO: Implement stream-json input
                return True
        
        try:
            response = await self.soul.chat(command)
            print(response)
            return True
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return False


__all__ = ["PrintUI", "InputFormat", "OutputFormat"]
