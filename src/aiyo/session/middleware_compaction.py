"""History compaction middleware."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .middleware_base import Middleware

if TYPE_CHECKING:
    from .history import HistoryManager

logger = logging.getLogger(__name__)


class CompactionMiddleware(Middleware):
    """Middleware that compacts history before each LLM call.

    Layer 1: micro_compact — shrink old tool results.
    Layer 2: deep_compact — LLM-summarize if still over token limit.
    """

    def __init__(self, history: "HistoryManager") -> None:
        self._history = history

    def before_llm_call(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Layer 1: shrink old tool results
        self._history.micro_compact()

        # Layer 2: full compact if still over token limit
        if self._history.count_tokens(self._history.get_history()) > self._history.effective_max:
            logger.warning("Token limit exceeded, triggering auto compact")
            status = self._history.deep_compact(Path(".history"))
            logger.info("Auto compact: %s", status)

        return self._history.get_history()
