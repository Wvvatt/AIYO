"""Conversation history management and compaction middleware."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .middleware import Middleware

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False
    logger.warning(
        "tiktoken not installed. Token counting will be estimated. "
        "Install with: pip install tiktoken"
    )


class HistoryManager:
    """Manages conversation history with token tracking and compression."""

    def __init__(
        self,
        max_tokens: int = 128000,
        reserve_tokens: int = 3000,
        model: str = "gpt-4o-mini",
        llm: Any = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            max_tokens: Maximum tokens allowed in history.
            reserve_tokens: Tokens to reserve for the LLM response.
            model: Model name for tokenization.
            llm: LLM instance for summarization in deep_compact.
        """
        self.max_tokens = max_tokens
        self._reserve_tokens = reserve_tokens
        self._model = model
        self._llm = llm

        # Initialize tokenizer if available
        self._tokenizer = None
        if _HAS_TIKTOKEN:
            try:
                self._tokenizer = tiktoken.encoding_for_model(model)
            except KeyError:
                # Model not in tiktoken, use cl100k_base (GPT-4)
                self._tokenizer = tiktoken.get_encoding("cl100k_base")

        self._history: list[dict[str, Any]] = []

    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens in a list of messages.

        Based on OpenAI's official token counting guide:
        https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb

        Supports both string content and multimodal content arrays.

        Args:
            messages: List of message dictionaries.

        Returns:
            Estimated token count.
        """
        if not messages:
            return 0

        if self._tokenizer:
            tokens = 0

            for msg in messages:
                # Base tokens per message (start token + role + \n + end token)
                tokens += 4

                # Count tokens for all fields in the message
                for key, value in msg.items():
                    if key == "role":
                        # Role already counted in base tokens (just \n)
                        tokens += len(self._tokenizer.encode(value))
                    elif key == "content":
                        if isinstance(value, str) and value:
                            tokens += len(self._tokenizer.encode(value))
                        elif isinstance(value, list):
                            # Multimodal content
                            for item in value:
                                if item.get("type") == "text":
                                    text = item.get("text", "")
                                    tokens += len(self._tokenizer.encode(text))
                                elif item.get("type") == "image_url":
                                    # Image token estimation: varies by detail level
                                    # Low detail: 85, High detail: 1000+
                                    tokens += 1000  # Conservative estimate
                    elif key == "name":
                        # Name field in function messages
                        tokens += len(self._tokenizer.encode(value))
                    elif key == "tool_call_id":
                        # Tool call ID in tool messages
                        tokens += len(self._tokenizer.encode(value))
                    elif key == "tool_calls":
                        # Tool calls in assistant messages
                        for tc in value:
                            # Base tokens for each tool call
                            tokens += 4
                            fn = tc.get("function", {})
                            for fn_key, fn_val in fn.items():
                                if isinstance(fn_val, str):
                                    tokens += len(self._tokenizer.encode(fn_val))
                            # Tool call ID
                            tc_id = tc.get("id")
                            if tc_id:
                                tokens += len(self._tokenizer.encode(tc_id))

            # Add overhead for assistant priming
            tokens += 3

            return tokens
        else:
            # Fallback: estimate ~4 chars per token + overhead
            total_chars = 0
            for msg in messages:
                for key, value in msg.items():
                    if key == "content":
                        if isinstance(value, str):
                            total_chars += len(value)
                        elif isinstance(value, list):
                            for item in value:
                                if item.get("type") == "text":
                                    total_chars += len(item.get("text", ""))
                                elif item.get("type") == "image_url":
                                    total_chars += 4000
                    elif isinstance(value, str):
                        total_chars += len(value)
                    elif isinstance(value, list):
                        total_chars += len(json.dumps(value, ensure_ascii=False))

            return (total_chars // 4) + len(messages) * 4 + 3

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to history.

        Args:
            message: Message dictionary with 'role' and 'content' keys.
        """
        self._history.append(message)

    def get_history(self) -> list[dict[str, Any]]:
        """Get the current message history.

        Returns:
            List of message dictionaries.
        """
        return self._history.copy()

    def clear(self) -> None:
        """Clear all history."""
        self._history.clear()

    async def deep_compact(
        self,
        transcript_dir: Path,
    ) -> str:
        """History compression via LLM summarization.

        Save full transcript to disk, call the summarizer to get a
        continuity summary, then replace history with that summary.

        Args:
            transcript_dir: Directory where the JSONL transcript is saved.

        Returns:
            A human-readable status message.
        """
        if self._llm is None:
            return "Layer 2 skipped: no LLM configured."

        # Save transcript
        transcript_dir.mkdir(exist_ok=True)
        transcript_path = transcript_dir / f"transcript_{int(time.time())}.jsonl"
        history = self._history.copy()
        with transcript_path.open("w", encoding="utf-8") as f:
            for msg in history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        # Summarize via LLM
        conversation_text = json.dumps(history, ensure_ascii=False)[:80000]
        try:
            summary = await self._summarize(conversation_text)
        except Exception as exc:
            return f"Deep compact failed: {exc}"

        # Replace history (keep system messages)
        system_messages = [m for m in self._history if m.get("role") == "system"]
        self._history.clear()
        self._history.extend(system_messages)
        self._history.append(
            {
                "role": "user",
                "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}",
            }
        )
        self._history.append(
            {
                "role": "assistant",
                "content": "Understood. I have the context from the summary. Continuing.",
            }
        )

        token_count = self.count_tokens(self._history)
        return (
            f"Compacted: transcript → {transcript_path}. "
            f"History now {token_count} tokens."
        )

    async def _summarize(self, conversation_text: str) -> str:
        """Call the LLM to produce a continuity summary."""
        response = await self._llm.acompletion(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this conversation for continuity. Include: "
                        "1) What was accomplished, 2) Current state, "
                        "3) Key decisions made. "
                        "Be concise but preserve critical details.\n\n" + conversation_text
                    ),
                }
            ],
            max_tokens=self._reserve_tokens,
        )
        return response.choices[0].message.content or ""

    def save(self, work_dir: Path) -> Path:
        """Save current history to <work_dir>/.history/history_YYYYMMDD_HHMMSS.jsonl.

        Args:
            work_dir: Root directory (settings.work_dir).

        Returns:
            Path of the saved file.
        """
        save_dir = work_dir / ".history"
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = save_dir / f"history_{timestamp}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for msg in self._history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return path

    @property
    def effective_max(self) -> int:
        """Effective maximum tokens after reserving space for response."""
        return self.max_tokens - self._reserve_tokens

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the current history state.

        Returns:
            Dictionary with history statistics.
        """
        token_count = self.count_tokens(self._history)

        role_counts: dict[str, int] = {}
        for msg in self._history:
            role = msg.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1

        return {
            "message_count": len(self._history),
            "token_count": token_count,
            "token_limit": self.max_tokens,
            "token_usage_percent": (token_count / self.max_tokens * 100)
            if self.max_tokens > 0
            else 0,
            "role_counts": role_counts,
        }


class CompactionMiddleware(Middleware):
    """Middleware that compacts history before each LLM call.

    Auto-compact: deep_compact — LLM-summarize if token limit exceeded.
    """

    def __init__(self, history: HistoryManager) -> None:
        self._history = history

    async def on_iteration_start(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current_tokens = self._history.count_tokens(self._history.get_history())
        if current_tokens > self._history.effective_max:
            logger.warning(
                "Token limit exceeded: %d / %d (effective max: %d), triggering auto compact",
                current_tokens,
                self._history.max_tokens,
                self._history.effective_max,
            )
            status = await self._history.deep_compact(Path(".history"))
            logger.info("Auto compact: %s", status)

        return self._history.get_history()
