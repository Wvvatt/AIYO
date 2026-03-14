"""Visualization for print mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ContentPart:
    type: Literal["text", "thinking"]
    content: str


class SimplePrinter:
    """Simple printer for output."""
    
    def __init__(self, output_format: str, final_only: bool = False):
        self.output_format = output_format
        self.final_only = final_only
        self._content: list[ContentPart] = []
    
    def feed(self, content: ContentPart) -> None:
        """Add content."""
        self._content.append(content)
    
    def flush(self) -> str:
        """Get final output."""
        result = ""
        for part in self._content:
            if part.type == "text":
                result += part.content
        return result
