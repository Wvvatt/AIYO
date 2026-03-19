"""Conversation history management for the AIYO agent."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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
        micro_compact_keep_recent: int = 10,
        llm: Any = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            max_tokens: Maximum tokens allowed in history.
            reserve_tokens: Tokens to reserve for the LLM response.
            model: Model name for tokenization.
            micro_compact_keep_recent: Number of recent tool results to keep intact during micro_compact.
            llm: LLM instance for summarization in deep_compact.
        """
        self.max_tokens = max_tokens
        self._reserve_tokens = reserve_tokens
        self._model = model
        self._micro_compact_keep_recent = micro_compact_keep_recent
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

        Supports both string content and multimodal content arrays.

        Args:
            messages: List of message dictionaries.

        Returns:
            Estimated token count.
        """
        if self._tokenizer:
            # Use tiktoken for accurate counting
            tokens = 0
            for msg in messages:
                # Count per message: ~4 tokens for structure + content
                tokens += 4
                content = msg.get("content")
                if isinstance(content, str) and content:
                    # Text-only message
                    tokens += len(self._tokenizer.encode(content))
                elif isinstance(content, list):
                    # Multimodal message (content is array)
                    for item in content:
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            tokens += len(self._tokenizer.encode(text))
                        elif item.get("type") == "image_url":
                            # Image token estimation
                            # Based on OpenAI vision pricing:
                            # - Low detail: 85 tokens
                            # - High detail: varies, use conservative estimate
                            tokens += 1000  # Conservative estimate
                if "tool_calls" in msg:
                    for tc in msg.get("tool_calls", []):
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            tokens += len(self._tokenizer.encode(fn["name"]))
                        if fn.get("arguments"):
                            tokens += len(self._tokenizer.encode(fn["arguments"]))
            return tokens
        else:
            # Fallback: estimate ~4 chars per token
            total_chars = 0
            for msg in messages:
                content = msg.get("content")
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            total_chars += len(item.get("text", ""))
                        elif item.get("type") == "image_url":
                            total_chars += 4000  # Rough estimate for image
                total_chars += len(str(msg.get("tool_calls", "")))
            return total_chars // 4

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

    def micro_compact(self) -> int:
        """Layer 1: Replace old tool results with short placeholders.

        Keeps the most recent *_micro_compact_keep_recent* tool-result messages intact and
        replaces the content of older ones with a one-line summary.

        Returns:
            Number of tool results that were replaced.
        """
        keep_recent = self._micro_compact_keep_recent
        tool_indices = [i for i, m in enumerate(self._history) if m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent:
            return 0

        # Build tool_call_id -> tool_name map from assistant messages
        tool_name_map: dict[str, str] = {}
        for msg in self._history:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tool_name_map[tc["id"]] = tc["function"]["name"]

        replaced = 0
        for idx in tool_indices[:-keep_recent]:
            msg = self._history[idx]
            content = msg.get("content", "")
            # Skip multimodal content (images) - don't compress those
            if isinstance(content, list):
                continue
            if len(str(content)) > 100:
                tool_name = tool_name_map.get(msg.get("tool_call_id", ""), "unknown")
                self._history[idx] = {**msg, "content": f"[Previous: used {tool_name}]"}
                replaced += 1

        if replaced:
            logger.debug("micro_compact: replaced %d old tool results", replaced)
        return replaced

    async def deep_compact(
        self,
        transcript_dir: Path,
    ) -> str:
        """Two-layer history compression.

        Layer 1 (micro): Replace old tool-result content with short placeholders.
        Layer 2 (auto):  Save full transcript to disk, call the summarizer to get a
                         continuity summary, then replace history with that summary.

        Args:
            transcript_dir: Directory where the JSONL transcript is saved.

        Returns:
            A human-readable status message.
        """
        if self._llm is None:
            replaced = self.micro_compact()
            return f"Layer 1 done ({replaced} replaced). Layer 2 skipped: no LLM configured."
        # Layer 1
        replaced = self.micro_compact()

        # Layer 2: save transcript
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
            return f"Layer 1 done ({replaced} replaced). Layer 2 failed: {exc}"

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
            f"Compacted: {replaced} tool results replaced (Layer 1), "
            f"transcript → {transcript_path} (Layer 2). "
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
