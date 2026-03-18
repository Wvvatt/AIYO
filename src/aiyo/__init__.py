"""AIYO — AI automation agent."""

from importlib.metadata import version

from .agent.agent import Agent
from .agent.middleware_base import Middleware
from .tools import WRITE_TOOLS

__version__ = version("aiyo")
__all__ = ["Agent", "Middleware", "WRITE_TOOLS", "__version__"]
