"""Analyze mode tools for Jira issue analysis workflow.

This module provides a structured workflow for Jira debugging:
- enter_analyze: Collects issue info and related context
- write_artifact: Allows LLM to write intermediate artifacts
- read_artifacts: Allows LLM to read previously written notes
- exit_analyze: Persists the final analysis conclusion and summary
"""

from __future__ import annotations

import asyncio
import json
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

from .jira_tools import JiraCredentials

logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class HistoryEntry:
    """Single entry in history.jsonl."""

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

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_jsonl_line(cls, line: str) -> HistoryEntry | None:
        try:
            data = json.loads(line.strip())
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

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


@dataclass
class LogFileIndex:
    """Index entry for a log file attachment."""

    path: str
    type: str  # log, archive, image, video, core_dump, config, other
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RelatedCase:
    """Related case info for case-based reasoning."""

    issue: str
    summary: str
    tags: list[str] = field(default_factory=list)
    similarity: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelatedCase:
        return cls(
            issue=data.get("issue", ""),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            similarity=data.get("similarity", 0),
            reason=data.get("reason", ""),
        )


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


def _get_history_path() -> Path:
    """Get the history file path (JSONL format)."""
    return _get_base_dir() / "history.jsonl"


def _get_attachments_dir(issue_key: str) -> Path:
    """Get the attachments directory for an issue."""
    return _get_issue_dir(issue_key) / "attachments"


def _get_artifacts_dir(issue_key: str) -> Path:
    """Get the artifacts directory for an issue."""
    return _get_issue_dir(issue_key) / "artifacts"


# ============================================================================
# File I/O Helpers
# ============================================================================
def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically to reduce partially-written artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _sanitize_issue_key(issue_key: str) -> str:
    """Normalize and validate a Jira issue key."""
    normalized = str(issue_key).upper().strip()
    if not normalized:
        raise ToolError("issue_key is required")
    return normalized


def _sanitize_artifact_name(name: str) -> str:
    """Map user-provided artifact names to safe markdown filenames."""
    safe_name = re.sub(r"[^\w\-_.]", "_", str(name).strip())
    if not safe_name:
        raise ToolError("name is required")
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    return safe_name


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


# ============================================================================
# History Management (JSONL)
# ============================================================================


def _load_history_entries() -> list[HistoryEntry]:
    """Load all history entries from history.jsonl."""
    history_path = _get_history_path()
    entries = []

    if not history_path.exists():
        return entries

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = HistoryEntry.from_jsonl_line(line)
                    if entry:
                        entries.append(entry)
    except OSError:
        pass

    return entries


def _upsert_history_entry(entry: HistoryEntry) -> None:
    """Insert or overwrite a history entry in history.jsonl by issue key."""
    history_path = _get_history_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_issue = entry.issue.upper().strip()
    new_line = entry.to_jsonl_line()

    lines: list[str] = []
    replaced = False

    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue

                    parsed = HistoryEntry.from_jsonl_line(stripped)
                    if (
                        parsed is not None
                        and parsed.issue.upper().strip() == normalized_issue
                    ):
                        if not replaced:
                            lines.append(new_line)
                            replaced = True
                        continue

                    # Preserve unreadable/legacy lines verbatim to avoid silent data loss.
                    lines.append(stripped)
        except OSError:
            pass

    if not replaced:
        lines.append(new_line)

    _atomic_write_text(history_path, "".join(line + "\n" for line in lines))


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


def _coarse_filter_candidates(
    issue_key: str,
    search_terms: list[str],
    entries: list[HistoryEntry],
    max_candidates: int = 30,
) -> list[HistoryEntry]:
    """Coarse filtering to reduce candidate set for sub-agent.

    Matches by tag overlap and keyword match in summary.
    """
    issue_key = issue_key.upper().strip()
    term_set = {_normalize_tag(t) for t in search_terms if _normalize_tag(t)}
    candidates = []

    for entry in entries:
        if entry.issue.upper() == issue_key:
            continue

        matched_tags: set[str] = set()

        # Tag match
        for tag in entry.tags:
            normalized_tag = _normalize_tag(tag)
            if normalized_tag and normalized_tag in term_set:
                matched_tags.add(normalized_tag)

        score = len(matched_tags) * 5

        # Keyword match in summary
        summary_lower = entry.summary.lower()
        for term in term_set:
            if term in summary_lower:
                score += 1

        if score > 0:
            candidates.append((entry, score))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [entry for entry, _ in candidates[:max_candidates]]


async def _find_related_cases_with_agent(
    current_summary: str,
    current_description: str,
    candidates: list[HistoryEntry],
    top_k: int = 5,
) -> tuple[list[RelatedCase], dict[str, Any]]:
    """Use a sub-agent to find related cases with semantic understanding."""
    if not candidates:
        return [], {"source": "none", "fallback_used": False, "warning": None}

    candidates_text = []
    for i, entry in enumerate(candidates, 1):
        candidates_text.append(
            f"Case {i}: [{entry.issue}] {entry.summary} (tags: {', '.join(entry.tags)})"
        )

    prompt = f"""You identify similar Jira debugging cases.

【Current Issue】
Summary: {current_summary}
Description: {current_description}

【Candidates】
{chr(10).join(candidates_text)}

Select the top {top_k} most relevant cases. Return a JSON array only:
[{{"issue": "XXX-123", "summary": "...", "tags": ["t1","t2"], "similarity": 85, "reason": "..."}}]
"""

    try:
        llm = AnyLLM.create(settings.provider)
        response = await llm.acompletion(
            model=settings.model_name,
            messages=[
                {
                    "role": "system",
                    "content": "Output ONLY valid JSON, no markdown formatting.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            max_tokens=settings.response_token_limit,
        )
        content = response.choices[0].message.content or ""

        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        data = json.loads(content)
        if not isinstance(data, list):
            return [], {
                "source": "empty_result",
                "fallback_used": True,
                "warning": "Related-case agent returned non-list JSON.",
            }

        results = [RelatedCase.from_dict(item) for item in data[:top_k] if isinstance(item, dict)]
        return results, {"source": "agent", "fallback_used": False, "warning": None}

    except Exception as exc:
        logger.warning("Related case agent failed; falling back to coarse candidates: %s", exc)
        return (
            [
                RelatedCase(
                    issue=entry.issue,
                    summary=entry.summary,
                    tags=entry.tags,
                    similarity=50,
                    reason="Based on tag matching",
                )
                for entry in candidates[:top_k]
            ],
            {
                "source": "coarse_filter_fallback",
                "fallback_used": True,
                "warning": f"Related-case ranking degraded: {exc}",
            },
        )


def _extract_preliminary_signals(text: str) -> list[str]:
    """Extract rough error signals from free text."""
    if not text:
        return []
    matches = re.findall(
        r"(error|fail|exception|panic|oops|BUG|WARNING)[\s\w:.-]*",
        text,
        re.IGNORECASE,
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for match in matches:
        cleaned = re.sub(r"\s+", " ", match).strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            deduped.append(cleaned)
            seen.add(lowered)
    return deduped


async def _generate_issue_tags(
    summary: str,
    description: str,
    components: list[str],
    labels: list[str],
) -> list[str]:
    """Generate 3 retrieval tags for the current issue."""
    context = f"""Summary: {summary}
Components: {", ".join(components) if components else "N/A"}
Labels: {", ".join(labels) if labels else "N/A"}
Description:
{description}"""
    return await _generate_tags_with_agent(context)


def _download_attachments(
    attachments: list[Any],
    attachments_dir: Path,
    creds: JiraCredentials,
) -> tuple[list[dict[str, Any]], list[LogFileIndex], list[str]]:
    """Download attachments and collect diagnostics."""
    attachments_info: list[dict[str, Any]] = []
    logs_index: list[LogFileIndex] = []
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
            if file_type == "log":
                logs_index.append(LogFileIndex(path=abs_path, type=file_type, size=file_size))
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

    return attachments_info, logs_index, warnings


# ============================================================================
# Main Tools
# ============================================================================
def _issue_key_summary(tool_args: dict[str, Any]) -> str:
    return str(tool_args.get("issue_key", ""))


def _artifact_summary(tool_args: dict[str, Any]) -> str:
    issue_key = str(tool_args.get("issue_key", ""))
    name = str(tool_args.get("name", ""))
    return f"{issue_key}/{name}" if issue_key or name else ""


@tool(summary=_issue_key_summary)
async def enter_analyze(issue_key: str) -> dict[str, Any]:
    """Enter analyze mode for a Jira issue.

    Creates workspace and collects all information including:
    - Jira issue details
    - Downloaded attachments with log index
    - Related historical cases

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123")

    Returns:
        Dict with structured data for analysis:
        - issue_key, workspace, summary, description
        - attachments, logs_index
        - existing_artifacts list
        - related_cases
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)
    attachments_dir = _get_attachments_dir(issue_key)
    artifacts_dir = _get_artifacts_dir(issue_key)
    warnings: list[str] = []
    degraded_flags: list[str] = []

    # Ensure directories exist
    attachments_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

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
    attachments_info, logs_index, attachment_warnings = _download_attachments(
        attachments,
        attachments_dir,
        creds,
    )
    if attachment_warnings:
        warnings.extend(attachment_warnings)
        degraded_flags.append("attachment_download_partial_failed")

    # List existing artifacts
    existing_artifacts = []
    if artifacts_dir.exists():
        for artifact_file in sorted(artifacts_dir.glob("*.md")):
            content = artifact_file.read_text(encoding="utf-8")
            existing_artifacts.append(
                {
                    "name": artifact_file.stem,
                    "size": len(content),
                    "preview": content[:200] + "..." if len(content) > 200 else content,
                }
            )

    # Find related cases using sub-agent
    history_entries = _load_history_entries()

    # Build search terms for coarse filtering from issue tags and local signals.
    preliminary_signals = _extract_preliminary_signals(description)
    issue_tags = await _generate_issue_tags(summary_text, description, components, labels)
    search_terms = [*issue_tags, *components, *labels, *preliminary_signals]

    coarse_candidates = _coarse_filter_candidates(issue_key, search_terms, history_entries)

    related_cases, related_case_diagnostics = await _find_related_cases_with_agent(
        summary_text, description, coarse_candidates, top_k=5
    )
    if related_case_diagnostics["warning"]:
        warnings.append(related_case_diagnostics["warning"])
    if related_case_diagnostics["fallback_used"]:
        degraded_flags.append("related_case_ranking_degraded")

    return {
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(settings.work_dir)),
        "summary": analysis_summary,
        "description": description,
        "comments": comments,
        "attachments": attachments_info,
        "logs_index": [li.to_dict() for li in logs_index],
        "existing_artifacts": existing_artifacts,
        "related_cases": [rc.to_dict() for rc in related_cases],
        "related_cases_source": related_case_diagnostics["source"],
        "warnings": warnings,
        "degraded": bool(degraded_flags),
        "degraded_flags": degraded_flags,
    }


@tool(summary=_artifact_summary)
async def write_artifact(
    issue_key: str,
    name: str,
    content: str,
) -> dict[str, Any]:
    """Write an intermediate artifact during analysis.

    Allows the LLM to save intermediate findings, preliminary analysis,
    or extracted knowledge during the analysis process.

    Args:
        issue_key: The Jira issue key
        name: Artifact name (e.g., "preliminary_findings", "module_knowledge")
        content: Artifact content (markdown/text)

    Returns:
        Dict with saved path and size
    """
    issue_key = _sanitize_issue_key(issue_key)
    artifacts_dir = _get_artifacts_dir(issue_key)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_artifact_name(name)
    artifact_path = artifacts_dir / safe_name
    _atomic_write_text(artifact_path, content)

    return {
        "saved_to": str(artifact_path.relative_to(settings.work_dir)),
        "size": len(content),
    }


@tool(summary=_artifact_summary)
async def read_artifacts(
    issue_key: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Read artifacts (notes) written during analysis.

    Allows the LLM to retrieve previously written notes, findings,
    or intermediate analysis results.

    Args:
        issue_key: The Jira issue key
        name: Optional artifact name to read specific file.
              If None, returns list of all artifacts.

    Returns:
        Dict with artifact content(s):
        - If name specified: returns specific artifact content
        - If name is None: returns list of all artifacts with previews
    """
    issue_key = _sanitize_issue_key(issue_key)
    artifacts_dir = _get_artifacts_dir(issue_key)

    if not artifacts_dir.exists():
        return {
            "issue_key": issue_key,
            "artifacts": [],
            "count": 0,
        }

    # Read specific artifact
    if name:
        safe_name = _sanitize_artifact_name(name)
        artifact_path = artifacts_dir / safe_name
        if not artifact_path.exists():
            return {
                "issue_key": issue_key,
                "name": name,
                "found": False,
                "content": None,
            }

        content = artifact_path.read_text(encoding="utf-8")
        return {
            "issue_key": issue_key,
            "name": name,
            "found": True,
            "content": content,
            "size": len(content),
            "saved_to": str(artifact_path.relative_to(settings.work_dir)),
        }

    # List all artifacts
    artifacts = []
    for artifact_file in sorted(artifacts_dir.glob("*.md")):
        content = artifact_file.read_text(encoding="utf-8")
        artifacts.append(
            {
                "name": artifact_file.stem,
                "size": len(content),
                "content": content,
                "saved_to": str(artifact_file.relative_to(settings.work_dir)),
            }
        )

    return {
        "issue_key": issue_key,
        "artifacts": artifacts,
        "count": len(artifacts),
    }


@tool(summary=_issue_key_summary)
async def exit_analyze(
    issue_key: str,
    conclusion: str,
) -> dict[str, Any]:
    """Exit analyze mode and persist the analysis conclusion.

    Generates a summary and 3 tags via two sub-agents, appends them to
    history.jsonl, saves the full conclusion to conclusion.md, and cleans up
    attachments.

    Args:
        issue_key: The Jira issue key
        conclusion: Free-form conclusion text for the current analysis session

    Returns:
        Dict with status and saved file paths
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)

    if not issue_dir.exists():
        raise ToolError(f"Workspace not found for {issue_key}. Did you call enter_analyze first?")

    conclusion = str(conclusion).strip()
    if not conclusion:
        raise ToolError("conclusion is required")

    saved_files: list[str] = []

    # 1. Generate summary/tags and upsert history.jsonl
    history_entry = await HistoryEntry.from_conclusion(issue_key, conclusion)
    _upsert_history_entry(history_entry)
    saved_files.append(str(_get_history_path().relative_to(settings.work_dir)))

    # 2. Save conclusion to conclusion.md
    conclusion_path = issue_dir / "conclusion.md"
    _atomic_write_text(conclusion_path, conclusion)
    saved_files.append(str(conclusion_path.relative_to(settings.work_dir)))

    # 3. Clean up downloaded attachments
    attachments_dir = _get_attachments_dir(issue_key)
    if attachments_dir.exists():
        shutil.rmtree(attachments_dir, ignore_errors=True)

    return {
        "status": "ok",
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(settings.work_dir)),
        "summary": history_entry.summary,
        "tags": history_entry.tags,
        "saved_files": saved_files,
    }
