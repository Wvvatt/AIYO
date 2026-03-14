"""AIYO — Amlogic AI automation agent."""

from .session import Session
from .tools import DEFAULT_TOOLS

# Backwards compatibility - Session was previously called Agent
Agent = Session

__all__ = ["Session", "Agent", "DEFAULT_TOOLS"]
