"""Analyze-mode domain models."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from aiyo.config import settings
from aiyo.tools.exceptions import ToolError
from any_llm import AnyLLM

logger = logging.getLogger(__name__)


def _sanitize_issue_key(issue_key: str) -> str:
    """Normalize and validate a Jira issue key."""
    normalized = str(issue_key).upper().strip()
    if not normalized:
        raise ToolError("issue_key is required")
    return normalized


def _normalize_tag(value: Any) -> str:
    """Normalize free-form text into a compact tag token."""
    tag = str(value).strip().lower()
    tag = re.sub(r"\s+", "-", tag)
    return re.sub(r"[^a-z0-9_.-]", "", tag)


async def _generate_tags_with_agent(context: str) -> list[str]:
    """Generate exactly 3 distinct tags by calling the agent 3 times."""
    llm = AnyLLM.create(settings.provider)

    tags: list[str] = []
    seen: set[str] = set()
    max_attempts = 9
    attempts = 0

    while len(tags) < 3 and attempts < max_attempts:
        attempts += 1
        existing = ", ".join(tags) if tags else "none"
        response = await llm.acompletion(
            model=settings.model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract exactly one concise retrieval tag from Jira text. "
                        "Output ONLY the tag text, with no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Extract exactly one short tag from the following text. "
                        "The tag should capture module, symptom, or root cause clue. "
                        f"Existing tags: {existing}. "
                        "Do not repeat existing tags. Output only the tag text.\n\n"
                        f"{context}"
                    ),
                },
            ],
            max_tokens=settings.response_token_limit,
        )
        content = response.choices[0].message.content or ""
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        tag = _normalize_tag(cleaned)
        if not tag or tag in seen:
            logger.warning("Ignoring invalid generated tag on attempt %d: %r", attempts, cleaned)
            continue
        tags.append(tag)
        seen.add(tag)

    if len(tags) != 3:
        raise ToolError(f"failed to generate 3 distinct tags after {attempts} attempts")

    return tags


@dataclass
class HistoryEntry:
    """Single entry in analyze-mode history memory."""

    issue: str
    summary: str
    tags: list[str] = field(default_factory=list)
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            issue=data.get("issue", ""),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            ts=data.get("ts", datetime.now().isoformat()),
        )

    @classmethod
    async def from_conclusion(cls, issue: str, conclusion: str) -> HistoryEntry:
        """Build a history entry from the final conclusion using two sub-agents."""

        async def _generate_summary() -> str:
            try:
                llm = AnyLLM.create(settings.provider)
                response = await llm.acompletion(
                    model=settings.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a summarization assistant. "
                                "Output ONLY a single concise sentence, nothing else."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Summarize the following analysis conclusion in one sentence "
                                f"(under 80 chars):\n\n{conclusion}"
                            ),
                        },
                    ],
                    max_tokens=settings.response_token_limit,
                )
                summary = response.choices[0].message.content or ""
                cleaned = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()
                return cleaned or summary.strip()
            except Exception as exc:
                logger.warning("Failed to generate history summary: %s", exc)
                first_line = conclusion.split("\n", 1)[0].strip()
                return first_line[:80] if len(first_line) > 80 else first_line

        async def _generate_tags() -> list[str]:
            try:
                return await _generate_tags_with_agent(conclusion)
            except Exception as exc:
                logger.warning("Failed to generate history tags: %s", exc)
                raise

        summary, tags = await asyncio.gather(_generate_summary(), _generate_tags())
        return cls(issue=_sanitize_issue_key(issue), summary=summary, tags=tags)


__all__ = ["HistoryEntry"]
