"""Analyze mode tools for Jira issue analysis workflow.

This module provides a structured workflow for Jira debugging:
- enter_analyze: Collects issue info and related context
- write_artifact: Allows LLM to write intermediate artifacts
- read_artifacts: Allows LLM to read previously written notes
- exit_analyze: Formats, validates, and persists structured analysis results
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from aiyo.config import settings
from aiyo.tools.exceptions import ToolError
from any_llm import AnyLLM
from pydantic import BaseModel, Field, model_validator

from .jira_tools import JiraCredentials

logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================


class AnalysisStructModel(BaseModel):
    """Canonical structured analysis model used for formatting and persistence."""

    summary: str = Field(default="")
    root_cause: str = Field(default="")
    signals: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    fix: str = Field(default="")
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, data: Any) -> Any:
        """Normalize untrusted LLM/tool input before model validation."""
        if not isinstance(data, dict):
            raise TypeError("analysis_struct must be a dict")

        def _normalize_text(value: Any) -> str:
            if value is None:
                return ""
            return str(value).strip()

        def _normalize_list(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                items = [value]
            elif isinstance(value, list):
                items = value
            else:
                raise TypeError("list-like field must be a list or string")

            normalized = []
            for item in items:
                text = _normalize_text(item)
                if text:
                    normalized.append(text)
            return normalized

        return {
            "summary": _normalize_text(data.get("summary")),
            "root_cause": _normalize_text(data.get("root_cause")),
            "signals": _normalize_list(data.get("signals")),
            "modules": _normalize_list(data.get("modules")),
            "fix": _normalize_text(data.get("fix")),
            "evidence": _normalize_list(data.get("evidence")),
        }

    def validate_business_rules(self) -> tuple[bool, list[str]]:
        """Validate business constraints beyond basic schema validation."""
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
        if any(not s.strip() for s in self.signals):
            errors.append("signals must contain non-empty strings only")
        if any(not m.strip() for m in self.modules):
            errors.append("modules must contain non-empty strings only")
        if not self.evidence:
            errors.append("evidence is empty (required: log snippets)")
        elif any(not ev.strip() for ev in self.evidence):
            errors.append("evidence must contain non-empty strings only")

        return len(errors) == 0, errors


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
    _atomic_write_text(path_obj, json.dumps(data, ensure_ascii=False, indent=2))


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


def _append_history_entry(entry: HistoryEntry) -> None:
    """Append a history entry to history.jsonl."""
    history_path = _get_history_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)

    with open(history_path, "a", encoding="utf-8") as f:
        f.write(entry.to_jsonl_line() + "\n")


def _is_same_history_entry(entry: HistoryEntry, other: HistoryEntry) -> bool:
    """Return whether two history entries represent the same analysis payload."""
    return (
        entry.issue.upper() == other.issue.upper()
        and entry.summary == other.summary
        and entry.root_cause == other.root_cause
        and entry.modules == other.modules
        and entry.signals == other.signals
        and entry.fix == other.fix
    )


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
) -> tuple[list[RelatedCase], dict[str, Any]]:
    """Use a sub-agent to find related cases with semantic understanding.

    Args:
        current_summary: Current issue summary
        current_description: Current issue description
        current_signals: Extracted signals from current logs
        candidates: Pre-filtered candidate entries
        top_k: Number of top results to return

    Returns:
        Tuple of related cases and diagnostics
    """
    if not candidates:
        return [], {"source": "none", "fallback_used": False, "warning": None}

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
            return [], {
                "source": "empty_result",
                "fallback_used": True,
                "warning": "Related-case agent returned non-list JSON.",
            }

        # Convert to RelatedCase objects
        results = []
        for item in data[:top_k]:
            if isinstance(item, dict):
                results.append(RelatedCase.from_dict(item))

        return results, {"source": "agent", "fallback_used": False, "warning": None}

    except Exception as exc:
        logger.warning("Related case agent failed; falling back to coarse candidates: %s", exc)
        # Fallback: return top candidates without agent ranking
        return (
            [
                RelatedCase(
                    issue=entry.issue,
                    summary=entry.summary,
                    root_cause=entry.root_cause,
                    signals=entry.signals,
                    similarity=50,
                    reason="Based on keyword/signal matching",
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


def _render_analysis_report(issue_key: str, struct: AnalysisStructModel) -> str:
    """Render a human-readable markdown report from a structured analysis."""
    report = f"""# Analysis Report - {issue_key}

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
        report += f"""### Evidence {i}
```
{ev}
```

"""
    return report


async def _format_analysis_with_agent(
    conclusion: str,
) -> tuple[AnalysisStructModel | None, dict[str, Any]]:
    """Format a free-form conclusion into the canonical analysis structure."""
    prompt = f"""You format Jira debugging conclusions into a strict structured object.

【Input Conclusion】
{conclusion}

【Task】
Extract a single structured result from the conclusion.
- summary: concise one-sentence summary, under 30 characters when possible
- root_cause: definitive root cause statement
- signals: list of concrete error keywords or symptoms
- modules: list of affected modules/components
- fix: concrete remediation or fix recommendation
- evidence: list of concrete evidence snippets quoted or summarized from the conclusion
- If a field is missing in the conclusion, return an empty string or empty list
- Do not invent evidence that is not supported by the conclusion
"""

    try:
        llm = AnyLLM.create(settings.provider)
        response = await llm.acompletion(
            model=settings.model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a structured Jira analysis result from the user's conclusion. "
                        "Be conservative and do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format=AnalysisStructModel,
            temperature=0,
            max_tokens=settings.response_token_limit,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("structured output returned no parsed content")
        struct = AnalysisStructModel.model_validate(parsed.model_dump())
        return struct, {"source": "response_format", "warning": None, "raw_response": None}
    except Exception as exc:
        logger.warning("Failed to format analysis conclusion: %s", exc)
        return None, {
            "source": "response_format_error",
            "warning": f"Failed to format conclusion into analysis struct: {exc}",
            "raw_response": None,
        }


# ============================================================================
# Main Tools
# ============================================================================
async def enter_analyze(issue_key: str) -> dict[str, Any]:
    """Enter analyze mode for a Jira issue.

    Creates workspace and collects all information including:
    - Jira issue details
    - Downloaded attachments with log index
    - Previous analysis data
    - Related historical cases

    Args:
        issue_key: The Jira issue key (e.g., "PROJ-123")

    Returns:
        Dict with structured data for analysis:
        - issue_key, workspace, summary, description
        - attachments, logs_index
        - existing_artifacts list
        - reference_analysis, related_cases
          reference_analysis is for reasoning only and must not be treated as the final answer
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)
    attachments_dir = issue_dir / "attachments"
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

    attachments = getattr(f, "attachment", []) or []
    attachments_info, logs_index, attachment_warnings = _download_attachments(
        attachments,
        attachments_dir,
        creds,
    )
    if attachment_warnings:
        warnings.extend(attachment_warnings)
        degraded_flags.append("attachment_download_partial_failed")

    previous_struct_data = _read_json_file(issue_dir / "analysis_struct.json")
    # Historical structured analysis is returned as reasoning context only.
    # The caller must still produce a fresh conclusion for the current issue state.
    reference_analysis = None
    if previous_struct_data:
        try:
            reference_analysis = AnalysisStructModel.model_validate(previous_struct_data)
        except Exception as exc:
            warnings.append(f"Failed to parse previous analysis_struct.json: {exc}")
            degraded_flags.append("reference_analysis_unreadable")

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

    # Extract preliminary signals from description for coarse filtering
    preliminary_signals = _extract_preliminary_signals(description)

    coarse_candidates = _coarse_filter_candidates(
        issue_key, components, preliminary_signals, history_entries
    )

    related_cases, related_case_diagnostics = await _find_related_cases_with_agent(
        summary_text, description, preliminary_signals, coarse_candidates, top_k=5
    )
    if related_case_diagnostics["warning"]:
        warnings.append(related_case_diagnostics["warning"])
    if related_case_diagnostics["fallback_used"]:
        degraded_flags.append("related_case_ranking_degraded")

    return {
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(Path.cwd())),
        "summary": analysis_summary,
        "description": description,
        "attachments": attachments_info,
        "logs_index": [li.to_dict() for li in logs_index],
        "reference_analysis": reference_analysis.model_dump() if reference_analysis else None,
        "existing_artifacts": existing_artifacts,
        "related_cases": [rc.to_dict() for rc in related_cases],
        "related_cases_source": related_case_diagnostics["source"],
        "has_history": bool(existing_artifacts),
        "warnings": warnings,
        "degraded": bool(degraded_flags),
        "degraded_flags": degraded_flags,
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
    issue_key = _sanitize_issue_key(issue_key)
    artifacts_dir = _get_artifacts_dir(issue_key)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_artifact_name(name)
    artifact_path = artifacts_dir / safe_name
    _atomic_write_text(artifact_path, content)

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
    conclusion: str,
) -> dict[str, Any]:
    """Exit analyze mode and save structured analysis artifacts.

    This is the ONLY way to complete an analysis. It formats the
    free-form conclusion into a structured result, validates it, and
    persists the final artifacts to the workspace.

    Args:
        issue_key: The Jira issue key
        conclusion: Free-form conclusion text for the current analysis session

    Returns:
        Dict with status and saved file paths, or validation errors
    """
    issue_key = _sanitize_issue_key(issue_key)
    issue_dir = _get_issue_dir(issue_key)

    if not issue_dir.exists():
        raise ToolError(f"Workspace not found for {issue_key}. Did you call enter_analyze first?")

    if not str(conclusion).strip():
        raise ToolError("conclusion is required")

    # Step 1: Format and validate the conclusion
    struct, formatter_meta = await _format_analysis_with_agent(str(conclusion).strip())
    if struct is None:
        return {
            "status": "error",
            "error_type": "parse_error",
            "message": "Failed to format conclusion into analysis_struct",
            "warnings": [formatter_meta["warning"]] if formatter_meta["warning"] else [],
            "draft_struct": None,
            "saved_files": [],
        }

    is_valid, errors = struct.validate_business_rules()
    if not is_valid:
        return {
            "status": "error",
            "error_type": "validation_error",
            "message": "analysis_struct validation failed",
            "errors": errors,
            "draft_struct": struct.model_dump(),
            "saved_files": [],
        }

    saved_files = []
    warnings: list[str] = []

    # Step 2: Generate artifacts from analysis_struct
    # 2.1 analysis_struct.json - canonical machine-readable analysis payload
    analysis_struct_path = issue_dir / "analysis_struct.json"
    _write_json_file(analysis_struct_path, struct.model_dump())
    saved_files.append(str(analysis_struct_path.relative_to(Path.cwd())))

    report_markdown = _render_analysis_report(issue_key, struct)

    # 2.2 history.jsonl - append structured entry unless it is an exact duplicate
    existing_entries = _load_history_entries()
    history_entry = HistoryEntry(
        issue=issue_key,
        summary=struct.summary,
        root_cause=struct.root_cause,
        tags=[],
        modules=struct.modules,
        signals=struct.signals,
        fix=struct.fix,
        confidence=0.9,
    )
    already_recorded = any(_is_same_history_entry(e, history_entry) for e in existing_entries)

    if not already_recorded:
        _append_history_entry(history_entry)
        saved_files.append(str(_get_history_path().relative_to(Path.cwd())))
    else:
        warnings.append(
            "Skipped appending history.jsonl because the same analysis was already recorded."
        )

    if not analysis_struct_path.exists():
        return {
            "status": "error",
            "error_type": "incomplete_artifacts",
            "message": "Required artifacts missing: ['analysis_struct.json']",
            "saved_files": saved_files,
        }

    return {
        "status": "ok",
        "issue_key": issue_key,
        "workspace": str(issue_dir.relative_to(Path.cwd())),
        "saved_files": saved_files,
        "warnings": warnings,
        "analysis_struct": struct.model_dump(),
        "report_markdown": report_markdown,
        "formatter_source": formatter_meta["source"],
    }
