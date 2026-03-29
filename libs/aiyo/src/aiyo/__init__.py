"""AIYO — AI automation agent."""

from importlib.metadata import version

__version__ = version("aiyo")

# Lazy imports to avoid slow startup
# Use: from aiyo.agent import Agent
#      from aiyo.tools import WRITE_TOOLS
__all__ = ["__version__"]
