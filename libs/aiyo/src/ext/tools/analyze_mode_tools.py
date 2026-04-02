"""Analyze mode tools for Jira issue analysis workflow.

This module provides a structured, sustainable learning system for Jira debugging:
- enter_analyze: Collects issue info with change detection
- write_artifact: Allows LLM to write intermediate artifacts
- read_artifacts: Allows LLM to read previously written notes
- exit_analyze: Validates and persists structured analysis results
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from aiyo.config import settings
from aiyo.tools.exceptions import ToolError

from .jira_tools import JiraCredentials

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class AnalysisStruct:
    """Unified analysis result structure."""

    summary: str  # One-sentence summary, < 30 chars
    root_cause: str  # Definitive root cause, no "maybe/suspect"
    signals: list[str] = field(default_factory=list)  # Error keywords, >= 1
    modules: list[str] = field(default_factory=list)  # Affected modules
    fix: str = ""  # Fix recommendation
    evidence: list[str] = field(default_factory=list)  # Log evidence snippets

    def validate(self) -> tuple[bool, list[str]]:
        """Validate the analysis struct against strict rules."""
        errors = []
        if not self.summary:
            errors.append("summary is empty (required: non-empty, < 30 chars)")
        elif len(self.summary) > 30:
            errors.append(f"summary too long ({len(self.summary)} chars, max 30)")

        if not self.root_cause:
            errors.append("root_cause is empty (required: definitive statement)")
        else:
            uncertain_words = [
                "可能",
                "怀疑",
                "或许",
                "maybe",
                "suspect",
                "perhaps",
                "probably",
                "might",
                "could be",
                "疑似",
            ]
            for word in uncertain_words:
                if word.lower() in self.root_cause.lower():
                    errors.append(f"root_cause contains uncertain expression: '{word}'")
                    break

        if len(self.signals) < 1:
            errors.append("signals must have at least 1 entry")
        if not self.evidence:
            errors.append("evidence is empty (required: log snippets)")

        return len(errors) == 0, errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreJiraInfo:
    """Jira issue snapshot for change detection."""

    issue_key: str
    summary: str = ""
    description: str = ""
    status: str = ""
    updated: str = ""
    comment_count: int = 0
    attachment_count: int = 0
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreJiraInfo:
        return cls(
            issue_key=data.get("issue_key", ""),
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            status=data.get("status", ""),
            updated=data.get("updated", ""),
            comment_count=data.get("comment_count", 0),
            attachment_count=data.get("attachment_count", 0),
            ts=data.get("ts", datetime.now().isoformat()),
        )


@dataclass
class HistoryEntry:
    """Single entry in history.jsonl."""

    issue: str
    summary: str
    root_cause: str
    tags: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    fix: str = ""
    confidence: float = 0.9
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            issue=data.get("issue", ""),
            summary=data.get("summary", ""),
            root_cause=data.get("root_cause", ""),
            tags=data.get("tags", []),
            modules=data.get("modules", []),
            signals=data.get("signals", []),
            fix=data.get("fix", ""),
            confidence=data.get("confidence", 0.9),
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
    root_cause: str
    signals: list[str] = field(default_factory=list)
    similarity: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelatedCase:
        return cls(
            issue=data.get("issue", ""),
            summary=data.get("summary", ""),
            root_cause=data.get("root_cause", ""),
            signals=data.get("signals", []),
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
    return Path.cwd() / ".jira-analysis"


def _get_issue_dir(issue_key: str) -> Path:
    """Get the directory for a specific issue."""
    return _get_base_dir() / issue_key.upper().strip()


def _get_history_path() -> Path:
    """Get the history file path (JSONL format)."""
    return _get_base_dir() / "history.jsonl"


def _get_artifacts_dir(issue_key: str) -> Path:
    """Get the artifacts directory for an issue."""
    return _get_issue_dir(issue_key) / "artifacts"


# ============================================================================
# File I/O Helpers
# ============================================================================
def _read_json_file(path: Path | str) -> dict[str, Any] | None:
    """Read a JSON file if it exists."""
    path_obj = Path(path)
    if not path_obj.exists():
        return None
    try:
        return json.loads(path_obj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json_file(path: Path | str, data: dict[str, Any]) -> None:
    """Write data to a JSON file."""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text_file(path: Path, max_size: int = 100000) -> str:
    """Read file content if exists, return empty string if not."""
    if not path.exists():
        return ""
    try:
        content = path.read_text(errors="ignore")
        if len(content) > max_size:
            return content[:max_size] + "\n...[truncated]"
        return content
    except Exception:
        return ""


# ============================================================================
# Change Detection
# ============================================================================
def _detect_changes(current: dict[str, Any], previous: PreJiraInfo | None) -> dict[str, Any]:
    """Detect changes between current Jira state and previous snapshot.

    Returns:
        Dict with 'unchanged' (bool), 'changes' (list), 'can_reuse_analysis' (bool)
    """
    if previous is None:
        return {"unchanged": False, "changes": ["no_previous_record"], "can_reuse_analysis": False}

    changes = []

    # Check key fields for changes
    if current.get("summary") != previous.summary:
        changes.append("summary")
    if current.get("description") != previous.description:
        changes.append("description")
    if current.get("updated") != previous.updated:
        changes.append("updated")
    if current.get("comment_count", 0) != previous.comment_count:
        changes.append("new_comments")
    if current.get("attachment_count", 0) != previous.attachment_count:
        changes.append("new_attachments")

    # Analysis can be reused if only metadata changed (not content)
    content_changes = set(changes) - {"updated"}
    can_reuse = len(content_changes) == 0 and len(changes) > 0

    return {"unchanged": len(changes) == 0, "changes": changes, "can_reuse_analysis": can_reuse}


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


def _append_history_entry(entry: HistoryEntry) -> None:
    """Append a history entry to history.jsonl."""
    history_path = _get_history_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)

    with open(history_path, "a", encoding="utf-8") as f:
        f.write(entry.to_jsonl_line() + "\n")


def _coarse_filter_candidates(
    issue_key: str,
    components: list[str],
    signals: list[str],
    entries: list[HistoryEntry],
    max_candidates: int = 30,
) -> list[HistoryEntry]:
    """Coarse filtering to reduce candidate set for sub-agent.

    Strategy:
    1. Match by module/component
    2. Match by signals overlap
    3. Sort by combined score
    """
    issue_key = issue_key.upper().strip()
    candidates = []

    # Build search terms
    search_terms = set(c.lower() for c in components)
    signal_set = set(s.lower() for s in signals)

    for entry in entries:
        # Skip self
        if entry.issue.upper() == issue_key:
            continue

        score = 0

        # Module match
        for module in entry.modules:
            if module.lower() in search_terms:
                score += 3

        # Signal match
        entry_signals = set(s.lower() for s in entry.signals)
        signal_overlap = len(signal_set & entry_signals)
        score += signal_overlap * 2

        # Keyword match in summary
        summary_lower = entry.summary.lower()
        for term in search_terms:
            if term in summary_lower:
                score += 1

        if score > 0:
            candidates.append((entry, score))

    # Sort by score and return top candidates
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [entry for entry, _ in candidates[:max_candidates]]


async def _find_related_cases_with_agent(
    current_summary: str,
    current_description: str,
    current_signals: list[str],
    candidates: list[HistoryEntry],
    top_k: int = 5,
) -> list[RelatedCase]:
    """Use a sub-agent to find related cases with semantic understanding.

    Args:
        current_summary: Current issue summary
        current_description: Current issue description
        current_signals: Extracted signals from current logs
        candidates: Pre-filtered candidate entries
        top_k: Number of top results to return

    Returns:
        List of RelatedCase with similarity scores and reasons
    """
    if not candidates:
        return []

    # Format candidates for the sub-agent
    candidates_text = []
    for i, entry in enumerate(candidates, 1):
        candidates_text.append(f"""
Case {i}:
- Issue: {entry.issue}
- Summary: {entry.summary}
- Root Cause: {entry.root_cause}
- Modules: {", ".join(entry.modules)}
- Signals: {", ".join(entry.signals)}
""")

    # Create sub-agent prompt
    prompt = f"""You are a professional Jira issue analysis assistant specializing in identifying similar debugging cases.

【Current Issue to Analyze】
Summary: {current_summary}
Description: {current_description}
Signals: {", ".join(current_signals)}

【Candidate Historical Cases】(pre-filtered)
{chr(10).join(candidates_text)}

【Task】
1. Analyze the core characteristics of the current issue (module, symptom, error type)
2. Evaluate the similarity (0-100) between each candidate case and the current issue
3. Select the top {top_k} most relevant cases
4. For each selected case, explain: Why is it relevant? Which signals match?

【Output Format】
Return a JSON array only, no markdown code blocks:
[
  {{
    "issue": "XXX-123",
    "summary": "brief summary",
    "root_cause": "root cause description",
    "signals": ["signal1", "signal2"],
    "similarity": 85,
    "reason": "explanation of relevance"
  }}
]
"""

    try:
        # Use aiyo Agent for sub-agent call
        from aiyo.agent.agent import Agent

        agent = Agent(
            system="You analyze Jira cases and return JSON arrays. Output ONLY valid JSON, no markdown formatting.",
            model=settings.model_name,
        )

        response = await agent.chat(prompt)

        # Parse JSON response
        # Try to extract JSON from response (in case there's extra text)
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if json_match:
            response = json_match.group(0)

        data = json.loads(response)

        if not isinstance(data, list):
            return []

        # Convert to RelatedCase objects
        results = []
        for item in data[:top_k]:
            if isinstance(item, dict):
                results.append(RelatedCase.from_dict(item))

        return results

    except Exception:
        # Fallback: return top candidates without agent ranking
        return [
            RelatedCase(
                issue=entry.issue,
                summary=entry.summary,
                root_cause=entry.root_cause,
                signals=entry.signals,
                similarity=50,
                reason="Based on keyword/signal matching",
            )
            for entry in candidates[:top_k]
        ]


# ============================================================================
# Main Tools
# ============================================================================
async def enter_analyze(issue_key: str) -> dict[str, Any]:
    """Enter analyze mode for a Jira issue.

    Creates workspace and collects all information including:
    - Jira issue details
    - Downloaded attachments with log index
    - Previous analysis data (artifacts, pre_jira_info)
    - Related historical cases
    - Change detection results

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123")

    Returns:
        Dict with structured data for analysis:
        - issue_key, workspace, summary, description
        - attachments, logs_index
        - pre_jira_info, existing_artifacts list
        - previous_analysis, related_cases
        - unchanged_since_last, detected_changes, can_reuse_analysis
    """
    if not issue_key:
        raise ToolError("issue_key is required")

    issue_key = issue_key.upper().strip()
    base_dir = _get_base_dir()
    issue_dir = _get_issue_dir(issue_key)
    attachments_dir = issue_dir / "attachments"
    artifacts_dir = _get_artifacts_dir(issue_key)

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
    summary_text = getattr(f, "summary", "")
    description = getattr(f, "description", "") or ""
    status = str(getattr(f, "status", "Unknown"))
    priority = str(getattr(f, "priority", "Unknown"))
    assignee = str(getattr(f, "assignee", "Unassigned"))
    reporter = str(getattr(f, "reporter", "Unknown"))
    labels = getattr(f, "labels", []) or []
    components = [str(c) for c in (getattr(f, "components", []) or [])]
    updated = str(getattr(f, "updated", ""))

    # Get comment count - handle PropertyHolder
    try:
        comments = getattr(f, "comment", None)
        comment_count = len(comments) if comments and hasattr(comments, "__len__") else 0
    except (TypeError, AttributeError):
        comment_count = 0

    # Build summary
    analysis_summary = f"""Issue: {issue_key}
Title: {summary_text}
Status: {status} | Priority: {priority}
Reporter: {reporter} | Assignee: {assignee}
Components: {", ".join(components) if components else "N/A"}
Labels: {", ".join(labels) if labels else "N/A"}"""

    # Download attachments and build log index
    attachments_info = []
    logs_index: list[LogFileIndex] = []

    try:
        attachments = getattr(f, "attachment", []) or []
        for att in attachments:
            filename = att.filename
            save_path = attachments_dir / filename

            # Download if not exists
            if not save_path.exists():
                try:
                    url = att.content
                    with httpx.Client(
                        auth=creds.http_auth(), follow_redirects=True, timeout=60
                    ) as client:
                        resp = client.get(url)
                        resp.raise_for_status()
                        save_path.write_bytes(resp.content)
                    file_size = len(resp.content)
                except Exception:
                    attachments_info.append(
                        {
                            "filename": filename,
                            "status": "download_failed",
                            "local_path": None,
                        }
                    )
                    continue
            else:
                file_size = save_path.stat().st_size

            # Classify file type
            file_type = "other"
            ext = filename.lower().split(".")[-1] if "." in filename else ""
            if ext in ["log", "txt", "dmesg"]:
                file_type = "log"
            elif ext in ["zip", "tar", "gz", "bz2", "xz"]:
                file_type = "archive"
            elif ext in ["png", "jpg", "jpeg", "bmp", "gif"]:
                file_type = "image"
            elif ext in ["mp4", "ts", "es", "avi", "mkv"]:
                file_type = "video"
            elif ext in ["core"]:
                file_type = "core_dump"
            elif ext in ["conf", "xml", "json", "yaml", "yml", "ini", "cfg"]:
                file_type = "config"

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

            # Add to logs_index if it's a log file
            if file_type == "log":
                logs_index.append(LogFileIndex(path=abs_path, type=file_type, size=file_size))
    except Exception:
        pass

    # Read previous analysis data
    pre_jira_info_data = _read_json_file(issue_dir / "pre_jira_info.json")
    pre_jira_info = PreJiraInfo.from_dict(pre_jira_info_data) if pre_jira_info_data else None

    previous_analysis = _read_text_file(issue_dir / "analysis.md")

    # List existing artifacts
    artifacts_dir = _get_artifacts_dir(issue_key)
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

    # Detect changes
    current_jira_state = {
        "summary": summary_text,
        "description": description,
        "status": status,
        "updated": updated,
        "comment_count": comment_count,
        "attachment_count": len(attachments_info),
    }
    change_detection = _detect_changes(current_jira_state, pre_jira_info)

    # Find related cases using sub-agent
    history_entries = _load_history_entries()

    # Extract preliminary signals from description for coarse filtering
    preliminary_signals = []
    error_patterns = re.findall(
        r"(error|fail|exception|panic|oops|BUG|WARNING)[\s\w:]*", description, re.IGNORECASE
    )
    preliminary_signals = list(set(error_patterns)) if error_patterns else []

    coarse_candidates = _coarse_filter_candidates(
        issue_key, components, preliminary_signals, history_entries
    )

    related_cases = await _find_related_cases_with_agent(
        summary_text, description, preliminary_signals, coarse_candidates, top_k=5
    )

    return {
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(Path.cwd())),
        "summary": analysis_summary,
        "description": description,
        "attachments": attachments_info,
        "logs_index": [li.to_dict() for li in logs_index],
        "pre_jira_info": pre_jira_info.to_dict() if pre_jira_info else None,
        "previous_analysis": previous_analysis,
        "existing_artifacts": existing_artifacts,
        "related_cases": [rc.to_dict() for rc in related_cases],
        "unchanged_since_last": change_detection["unchanged"],
        "detected_changes": change_detection["changes"],
        "can_reuse_analysis": change_detection["can_reuse_analysis"] and bool(previous_analysis),
        "has_history": bool(existing_artifacts),
    }


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
    if not issue_key:
        raise ToolError("issue_key is required")
    if not name:
        raise ToolError("name is required")

    issue_key = issue_key.upper().strip()
    artifacts_dir = _get_artifacts_dir(issue_key)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = re.sub(r"[^\w\-_.]", "_", name)
    if not safe_name.endswith(".md"):
        safe_name += ".md"

    artifact_path = artifacts_dir / safe_name
    artifact_path.write_text(content, encoding="utf-8")

    return {
        "saved_to": str(artifact_path.relative_to(Path.cwd())),
        "size": len(content),
    }


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
    if not issue_key:
        raise ToolError("issue_key is required")

    issue_key = issue_key.upper().strip()
    artifacts_dir = _get_artifacts_dir(issue_key)

    if not artifacts_dir.exists():
        return {
            "issue_key": issue_key,
            "artifacts": [],
            "count": 0,
        }

    # Read specific artifact
    if name:
        safe_name = re.sub(r"[^\w\-_.]", "_", name)
        if not safe_name.endswith(".md"):
            safe_name += ".md"

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
            "saved_to": str(artifact_path.relative_to(Path.cwd())),
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
                "saved_to": str(artifact_file.relative_to(Path.cwd())),
            }
        )

    return {
        "issue_key": issue_key,
        "artifacts": artifacts,
        "count": len(artifacts),
    }


async def exit_analyze(
    issue_key: str,
    analysis_struct: dict[str, Any],
) -> dict[str, Any]:
    """Exit analyze mode and save structured analysis artifacts.

    This is the ONLY way to complete an analysis. It validates the
    analysis_struct, generates all artifacts from it, and persists
    them to the workspace.

    Args:
        issue_key: The Jira issue key
        analysis_struct: Unified analysis result structure with:
            - summary: str (< 30 chars)
            - root_cause: str (definitive, no uncertain words)
            - signals: list[str] (>= 1)
            - modules: list[str]
            - fix: str
            - evidence: list[str] (non-empty)

    Returns:
        Dict with status and saved file paths, or validation errors
    """
    if not issue_key:
        raise ToolError("issue_key is required")

    issue_key = issue_key.upper().strip()
    issue_dir = _get_issue_dir(issue_key)

    if not issue_dir.exists():
        raise ToolError(f"Workspace not found for {issue_key}. Did you call enter_analyze first?")

    # Step 1: Parse and validate analysis_struct
    try:
        struct = AnalysisStruct.from_dict(analysis_struct)
    except Exception as e:
        return {
            "status": "error",
            "error_type": "parse_error",
            "message": f"Failed to parse analysis_struct: {e}",
            "saved_files": [],
        }

    is_valid, errors = struct.validate()
    if not is_valid:
        return {
            "status": "error",
            "error_type": "validation_error",
            "message": "analysis_struct validation failed",
            "errors": errors,
            "saved_files": [],
        }

    saved_files = []

    # Step 2: Generate artifacts from analysis_struct

    # 2.1 pre_jira_info.json - current Jira snapshot for change detection
    # Fetch current Jira info
    try:
        creds = JiraCredentials()
        jira = creds.client()
        issue = jira.issue(
            issue_key, fields="summary,description,status,updated,comment,attachment"
        )
        f = issue.fields

        # Safely get comment count
        try:
            comments = getattr(f, "comment", None)
            comment_count = len(comments) if comments and hasattr(comments, "__len__") else 0
        except (TypeError, AttributeError):
            comment_count = 0

        # Safely get attachment count
        try:
            attachments = getattr(f, "attachment", None)
            attachment_count = (
                len(attachments) if attachments and hasattr(attachments, "__len__") else 0
            )
        except (TypeError, AttributeError):
            attachment_count = 0

        pre_jira_info = PreJiraInfo(
            issue_key=issue_key,
            summary=getattr(f, "summary", ""),
            description=getattr(f, "description", "") or "",
            status=str(getattr(f, "status", "")),
            updated=str(getattr(f, "updated", "")),
            comment_count=comment_count,
            attachment_count=attachment_count,
        )
        jira_info_path = issue_dir / "pre_jira_info.json"
        _write_json_file(jira_info_path, pre_jira_info.to_dict())
        saved_files.append(str(jira_info_path.relative_to(Path.cwd())))
    except Exception:
        pass  # Non-critical, continue

    # 2.2 analysis.md - human-readable report
    analysis_content = f"""# Analysis Report - {issue_key}

**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Summary
{struct.summary}

## Root Cause
{struct.root_cause}

## Signals Detected
{chr(10).join(f"- {s}" for s in struct.signals)}

## Affected Modules
{chr(10).join(f"- {m}" for m in struct.modules) if struct.modules else "N/A"}

## Fix Recommendation
{struct.fix}

## Evidence

"""
    for i, ev in enumerate(struct.evidence, 1):
        analysis_content += f"""### Evidence {i}
```
{ev}
```

"""

    analysis_path = issue_dir / "analysis.md"
    analysis_path.write_text(analysis_content, encoding="utf-8")
    saved_files.append(str(analysis_path.relative_to(Path.cwd())))

    # 2.3 history.jsonl - append structured entry
    # Check if already exists to avoid duplicates
    existing_entries = _load_history_entries()
    already_recorded = any(e.issue.upper() == issue_key for e in existing_entries)

    if not already_recorded:
        history_entry = HistoryEntry(
            issue=issue_key,
            summary=struct.summary,
            root_cause=struct.root_cause,
            tags=[],
            modules=struct.modules,
            signals=struct.signals,
            fix=struct.fix,
            confidence=0.9,  # Could be made configurable
        )
        _append_history_entry(history_entry)

    # Step 3: Verify required artifacts exist
    required_files = [
        issue_dir / "analysis.md",
    ]

    missing = [f.name for f in required_files if not f.exists()]
    if missing:
        return {
            "status": "error",
            "error_type": "incomplete_artifacts",
            "message": f"Required artifacts missing: {missing}",
            "saved_files": saved_files,
        }

    return {
        "status": "ok",
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(Path.cwd())),
        "saved_files": saved_files,
    }
