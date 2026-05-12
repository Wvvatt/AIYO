"""Analyze mode tools for Jira issue analysis workflow.

This module provides a structured workflow for Jira debugging:
- enter_analyze: Collects issue info and related context
- exit_analyze: Persists the final analysis conclusion and summary
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx
from aiyo.config import settings
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError

from ext.infra.analyze_models import HistoryEntry
from ext.infra.credentials import JiraCredentials

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


def _get_jira_client() -> tuple[JiraCredentials, Any]:
    """Build Jira credentials and client for analyze mode."""
    try:
        creds = JiraCredentials()
        return creds, creds.client()
    except KeyError as exc:
        raise ToolError(f"Jira credentials not configured: {exc}") from exc
    except Exception as exc:
        raise ToolError(f"Failed to initialize Jira client: {exc}") from exc


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


def _reset_issue_workspace(issue_dir: Path, attachments_dir: Path) -> None:
    """Reset the local analyze workspace for one issue."""
    if issue_dir.exists():
        shutil.rmtree(issue_dir, ignore_errors=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)


def _fetch_issue(jira: Any, issue_key: str) -> Any:
    """Fetch one Jira issue with the fields needed by analyze mode."""
    try:
        issue = jira.issue(
            issue_key,
            fields=(
                "summary,description,status,priority,assignee,reporter,labels,"
                "components,attachment,comment,updated"
            ),
        )
    except Exception as exc:
        raise ToolError(f"Failed to fetch issue {issue_key}: {exc}") from exc
    return issue.fields


def _build_analysis_summary(issue_key: str, fields: Any) -> str:
    """Build the compact issue summary shown to the model."""
    summary_text = getattr(fields, "summary", "") or ""
    status = str(getattr(fields, "status", "Unknown"))
    priority = str(getattr(fields, "priority", "Unknown"))
    assignee = str(getattr(fields, "assignee", "Unassigned"))
    reporter = str(getattr(fields, "reporter", "Unknown"))
    labels = getattr(fields, "labels", []) or []
    components = [str(component) for component in (getattr(fields, "components", []) or [])]
    return f"""Issue: {issue_key}
Title: {summary_text}
Status: {status} | Priority: {priority}
Reporter: {reporter} | Assignee: {assignee}
Components: {", ".join(components) if components else "N/A"}
Labels: {", ".join(labels) if labels else "N/A"}"""


def _extract_comments(raw_comments: Any) -> list[dict[str, str]]:
    """Normalize Jira comments into a simple JSON-friendly shape."""
    if not raw_comments:
        return []

    comments: list[dict[str, str]] = []
    for comment in getattr(raw_comments, "comments", raw_comments) or []:
        body = getattr(comment, "body", "") or ""
        if not body.strip():
            continue
        comments.append(
            {
                "author": str(getattr(comment, "author", "Unknown")),
                "created": str(getattr(comment, "created", "")),
                "body": body,
            }
        )
    return comments


def _format_history_entry(entry: HistoryEntry) -> str:
    """Render a compact history entry as the summary only."""
    return entry.summary


@tool(summary=_issue_key_summary)
async def enter_analyze(issue_key: str) -> dict[str, Any]:
    """Enter analyze mode for a Jira issue.

    Creates workspace and collects all information including:
    - Jira issue details
    - Downloaded attachments

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123")

    Returns:
        Dict with structured data for analysis:
        - issue_key, workspace, summary, description
        - attachments
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)
    attachments_dir = _get_attachments_dir(issue_key)
    warnings: list[str] = []

    # Local workspace is a throwaway cache. Reset it so stale attachments or
    # previous cache files do not pollute a new analysis run.
    _reset_issue_workspace(issue_dir, attachments_dir)
    creds, jira = _get_jira_client()
    fields = _fetch_issue(jira, issue_key)
    attachments = getattr(fields, "attachment", []) or []
    attachments_info, attachment_warnings = _download_attachments(
        attachments,
        attachments_dir,
        creds,
    )
    if attachment_warnings:
        warnings.extend(attachment_warnings)

    return {
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(settings.work_dir)),
        "summary": _build_analysis_summary(issue_key, fields),
        "description": getattr(fields, "description", "") or "",
        "comments": _extract_comments(getattr(fields, "comment", None)),
        "attachments": attachments_info,
        "warnings": warnings,
    }


@tool(summary=_issue_key_summary)
async def exit_analyze(
    issue_key: str,
    conclusion: str,
) -> dict[str, Any]:
    """Exit analyze mode and summarize the analysis conclusion.

    The `conclusion` is used only to derive the history `summary` and `tags`.
    The full conclusion is not persisted by this tool; memory persistence is
    expected to be handled by the configured MCP memory tools. This tool cleans
    up any local temporary attachments.

    Args:
        issue_key: The Jira issue key
        conclusion: Free-form conclusion text for the current analysis session

    Returns:
        Dict with status, derived summary, and derived tags
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)

    conclusion = str(conclusion).strip()
    if not conclusion:
        raise ToolError("conclusion is required")

    history_entry = await HistoryEntry.from_conclusion(issue_key, conclusion)

    if issue_dir.exists():
        shutil.rmtree(issue_dir, ignore_errors=True)

    return {
        "status": "ok",
        "issue_key": issue_key,
        "summary": history_entry.summary,
        "tags": history_entry.tags,
    }
