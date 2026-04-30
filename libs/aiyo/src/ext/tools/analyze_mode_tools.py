"""Analyze mode tools for Jira issue analysis workflow.

This module provides a structured workflow for Jira debugging:
- enter_analyze: Collects issue info and related context
- upsert_artifact: Allows LLM to write or replace intermediate artifacts
- exit_analyze: Persists the final analysis conclusion and summary
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from aiyo.config import settings
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError
from any_llm import AnyLLM

from ext.clients.confluence_memory import ConfluenceMemory
from ext.config import ExtSettings

from .confluence_tools import ConfluenceCredentials
from .jira_tools import JiraCredentials

logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================


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


# ============================================================================
# Path Helpers
# ============================================================================


def _get_base_dir() -> Path:
    """Get the base analysis directory.

    Stored in .jira-analysis/ under current working directory.
    """
    return settings.work_dir / ".jira-analysis"


def _get_issue_dir(issue_key: str) -> Path:
    """Get the directory for a specific issue."""
    return _get_base_dir() / issue_key.upper().strip()


def _get_attachments_dir(issue_key: str) -> Path:
    """Get the attachments directory for an issue."""
    return _get_issue_dir(issue_key) / "attachments"


def _sanitize_issue_key(issue_key: str) -> str:
    """Normalize and validate a Jira issue key."""
    normalized = str(issue_key).upper().strip()
    if not normalized:
        raise ToolError("issue_key is required")
    return normalized


def _classify_attachment_type(filename: str) -> str:
    """Classify attachment type based on filename extension."""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext in ["log", "txt", "dmesg"]:
        return "log"
    if ext in ["zip", "tar", "gz", "bz2", "xz"]:
        return "archive"
    if ext in ["png", "jpg", "jpeg", "bmp", "gif"]:
        return "image"
    if ext in ["mp4", "ts", "es", "avi", "mkv"]:
        return "video"
    if ext in ["core"]:
        return "core_dump"
    if ext in ["conf", "xml", "json", "yaml", "yml", "ini", "cfg"]:
        return "config"
    return "other"


def _get_memory() -> ConfluenceMemory:
    """Build the Confluence-backed memory client for analyze mode."""
    cfg = ExtSettings()
    if not cfg.confluence_artifact_page_id or not cfg.confluence_history_page_id:
        raise ToolError(
            "CONFLUENCE_ARTIFACT_PAGE_ID and CONFLUENCE_HISTORY_PAGE_ID must be configured "
            "for analyze-mode memory."
        )

    try:
        client = ConfluenceCredentials().client()
    except KeyError as exc:
        raise ToolError(f"Confluence credentials not configured: {exc}") from exc

    return ConfluenceMemory(
        client=client,
        artifact_root_page_id=cfg.confluence_artifact_page_id,
        history_page_id=cfg.confluence_history_page_id,
    )


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


def _download_attachments(
    attachments: list[Any],
    attachments_dir: Path,
    creds: JiraCredentials,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Download attachments and collect diagnostics."""
    attachments_info: list[dict[str, Any]] = []
    warnings: list[str] = []

    for att in attachments:
        filename = getattr(att, "filename", "") or "unknown"
        save_path = attachments_dir / filename
        file_type = _classify_attachment_type(filename)

        try:
            if not save_path.exists():
                url = att.content
                with httpx.Client(
                    auth=creds.http_auth(), follow_redirects=True, timeout=60
                ) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    save_path.write_bytes(resp.content)
                file_size = len(resp.content)
            else:
                file_size = save_path.stat().st_size

            abs_path = str(save_path)
            attachments_info.append(
                {
                    "filename": filename,
                    "size": file_size,
                    "type": file_type,
                    "status": "downloaded",
                    "local_path": abs_path,
                }
            )
        except Exception as exc:
            warnings.append(f"Failed to download attachment '{filename}': {exc}")
            attachments_info.append(
                {
                    "filename": filename,
                    "type": file_type,
                    "status": "download_failed",
                    "local_path": None,
                    "error": str(exc),
                }
            )

    return attachments_info, warnings


# ============================================================================
# Main Tools
# ============================================================================
def _issue_key_summary(tool_args: dict[str, Any]) -> str:
    return str(tool_args.get("issue_key", ""))


def _artifact_summary(tool_args: dict[str, Any]) -> str:
    issue_key = str(tool_args.get("issue_key", ""))
    title = str(tool_args.get("title", ""))
    return f"{issue_key}/{title}" if issue_key or title else ""


def _write_history_cache(issue_key: str, memory: ConfluenceMemory) -> Path:
    """Download the raw Confluence history page storage into a local cache file."""
    history_path = _get_issue_dir(issue_key) / "history.xml"
    page = memory.client.get_page_by_id(memory.history_page_id, expand="body.storage")
    if not isinstance(page, dict):
        raise ToolError(f"Confluence history page '{memory.history_page_id}' not found.")

    body = page.get("body", {}).get("storage", {}).get("value") or ""
    history_path.write_text(str(body), encoding="utf-8")
    return history_path


def _write_artifact_cache(issue_key: str, memory: ConfluenceMemory) -> Path:
    """Download the raw artifact page storage into a local cache file."""
    artifact_path = _get_issue_dir(issue_key) / "artifacts.xml"
    artifact_page = memory.get_artifact_page_storage(issue_key)
    if artifact_page is None:
        artifact_path.write_text("", encoding="utf-8")
        return artifact_path

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(artifact_page["content"], encoding="utf-8")
    return artifact_path


@tool(summary=_issue_key_summary)
async def enter_analyze(issue_key: str) -> dict[str, Any]:
    """Enter analyze mode for a Jira issue.

    Creates workspace and collects all information including:
    - Jira issue details
    - Downloaded attachments
    - Raw history page cache downloaded from Confluence

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123")

    Returns:
        Dict with structured data for analysis:
        - issue_key, workspace, summary, description
        - attachments
        - history_path / artifacts_path for local grep/read access
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)
    attachments_dir = _get_attachments_dir(issue_key)
    warnings: list[str] = []
    memory = _get_memory()

    # Local workspace is a throwaway cache. Reset it so stale attachments or
    # previous cache files do not pollute a new analysis run.
    if issue_dir.exists():
        shutil.rmtree(issue_dir, ignore_errors=True)

    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Jira client
    try:
        creds = JiraCredentials()
        jira = creds.client()
    except KeyError as e:
        raise ToolError(f"Jira credentials not configured: {e}")

    # Fetch issue details
    try:
        issue = jira.issue(
            issue_key,
            fields="summary,description,status,priority,assignee,reporter,labels,components,attachment,comment,updated",
        )
        f = issue.fields
    except Exception as e:
        raise ToolError(f"Failed to fetch issue {issue_key}: {e}")

    # Extract basic info
    summary_text = getattr(f, "summary", "") or ""
    description = getattr(f, "description", "") or ""
    status = str(getattr(f, "status", "Unknown"))
    priority = str(getattr(f, "priority", "Unknown"))
    assignee = str(getattr(f, "assignee", "Unassigned"))
    reporter = str(getattr(f, "reporter", "Unknown"))
    labels = getattr(f, "labels", []) or []
    components = [str(c) for c in (getattr(f, "components", []) or [])]

    # Build summary
    analysis_summary = f"""Issue: {issue_key}
Title: {summary_text}
Status: {status} | Priority: {priority}
Reporter: {reporter} | Assignee: {assignee}
Components: {", ".join(components) if components else "N/A"}
Labels: {", ".join(labels) if labels else "N/A"}"""

    # Extract comments
    raw_comments = getattr(f, "comment", None)
    comments = []
    if raw_comments:
        for c in getattr(raw_comments, "comments", raw_comments) or []:
            author = str(getattr(c, "author", "Unknown"))
            body = getattr(c, "body", "") or ""
            created = getattr(c, "created", "")
            if body.strip():
                comments.append({"author": author, "created": created, "body": body})

    attachments = getattr(f, "attachment", []) or []
    attachments_info, attachment_warnings = _download_attachments(
        attachments,
        attachments_dir,
        creds,
    )
    if attachment_warnings:
        warnings.extend(attachment_warnings)

    history_path = _write_history_cache(issue_key, memory)
    artifacts_path = _write_artifact_cache(issue_key, memory)

    return {
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(settings.work_dir)),
        "summary": analysis_summary,
        "description": description,
        "comments": comments,
        "attachments": attachments_info,
        "history_path": str(history_path.relative_to(settings.work_dir)),
        "artifacts_path": str(artifacts_path.relative_to(settings.work_dir)),
        "warnings": warnings,
    }


@tool(summary=_artifact_summary)
async def upsert_artifact(
    issue_key: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    """Create or replace an intermediate artifact during analysis.

    Stores one artifact section on the issue's Confluence page. If another
    artifact with the same title already exists for the issue, its content is
    replaced in place instead of appending a duplicate entry.

    Args:
        issue_key: The Jira issue key
        title: Artifact title (e.g., "preliminary_findings", "module_knowledge")
        content: Artifact content in raw text format

    Returns:
        Dict with Confluence child page metadata and content size
    """
    issue_key = _sanitize_issue_key(issue_key)
    title = str(title).strip()
    if not title:
        raise ToolError("title is required")

    result = _get_memory().upsert_artifact(issue_key, title, content)

    return {
        "child_page_id": result["child_page_id"],
        "child_page_url": result["child_page_url"],
        "row_index": result["row_index"],
        "updated": result["updated"],
        "size": len(content),
    }


@tool(summary=_issue_key_summary)
async def exit_analyze(
    issue_key: str,
    conclusion: str,
) -> dict[str, Any]:
    """Exit analyze mode and persist the analysis conclusion.

    The `conclusion` is used only to derive the history `summary` and `tags`.
    The full conclusion is not persisted; this tool writes only summary and tags
    to Confluence history memory, then cleans up any local temporary attachments.

    Args:
        issue_key: The Jira issue key
        conclusion: Free-form conclusion text for the current analysis session

    Returns:
        Dict with status, derived summary/tags, and history page metadata
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)

    conclusion = str(conclusion).strip()
    if not conclusion:
        raise ToolError("conclusion is required")

    history_entry = await HistoryEntry.from_conclusion(issue_key, conclusion)
    memory = _get_memory()
    memory.upsert_history(issue_key, history_entry.summary, history_entry.tags)

    if issue_dir.exists():
        shutil.rmtree(issue_dir, ignore_errors=True)

    return {
        "status": "ok",
        "issue_key": issue_key,
        "summary": history_entry.summary,
        "tags": history_entry.tags,
        "history_page_id": memory.history_page_id,
    }
