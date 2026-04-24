"""Jira tools.

Auth is read from environment variables (or .env file):
  JIRA_SERVER   — Jira instance URL
  JIRA_USERNAME — username or email
  JIRA_PASSWORD — password or API token
"""

import json
from pathlib import Path
from typing import Any

import httpx
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError
from jira import JIRA, JIRAError

from ext.config import ExtSettings
from ext.tools._health_cache import cached_health


async def health() -> dict[str, Any]:
    """Check Jira connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    async def _probe() -> dict[str, Any]:
        cfg = ExtSettings()
        if not cfg.jira_server:
            return {"name": "jira", "status": "not_configured", "message": "JIRA_SERVER missing"}
        if not cfg.jira_username:
            return {"name": "jira", "status": "not_configured", "message": "JIRA_USERNAME missing"}
        if not cfg.jira_password:
            return {"name": "jira", "status": "not_configured", "message": "JIRA_PASSWORD missing"}

        try:
            async with httpx.AsyncClient(
                auth=(cfg.jira_username, cfg.jira_password),
                follow_redirects=True,
                timeout=10,
            ) as client:
                resp = await client.get(f"{cfg.jira_server.rstrip('/')}/rest/api/2/myself")
                resp.raise_for_status()
            return {"name": "jira", "status": "ok", "message": cfg.jira_server}
        except Exception as e:
            return {"name": "jira", "status": "error", "message": str(e)}

    return await cached_health("jira", _probe)


class JiraCredentials:
    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.jira_server
        self.username = cfg.jira_username
        self.password = cfg.jira_password
        if not self.username:
            raise KeyError("JIRA_USERNAME")
        if not self.password:
            raise KeyError("JIRA_PASSWORD")

    def client(self) -> JIRA:
        return JIRA(server=self.server, basic_auth=(self.username, self.password))

    def http_auth(self) -> tuple[str, str]:
        return (self.username, self.password)


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _credentials_and_client() -> tuple[JiraCredentials, JIRA]:
    try:
        creds = JiraCredentials()
        return creds, creds.client()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Jira credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  JIRA_SERVER=https://your-jira.example.com\n"
            "  JIRA_USERNAME=your-username\n"
            "  JIRA_PASSWORD=your-password-or-api-token\n"
        ) from e


def _jira_error(exc: Exception) -> ToolError:
    if isinstance(exc, JIRAError):
        return ToolError(f"Jira error {exc.status_code}: {exc.text}")
    if isinstance(exc, KeyError):
        return ToolError(f"missing required arg '{str(exc).strip(chr(39) + chr(34))}'.")
    if isinstance(exc, ToolError):
        return exc
    return ToolError(str(exc))


def _field_summary(*names: str):
    def summary(tool_args: dict[str, Any]) -> str:
        return " ".join(str(tool_args.get(name)) for name in names if tool_args.get(name))

    return summary


def _normalize_fields(value: Any) -> str | None:
    """Normalize weak-model field filters into Jira's comma-separated format."""
    if not value:
        return None
    if isinstance(value, str):
        raw = value.strip()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [part.strip() for part in raw.split(",")]
        value = parsed
    if isinstance(value, list):
        aliases = {"issueType": "issuetype", "issue_type": "issuetype"}
        fields = [aliases.get(str(field), str(field)) for field in value if str(field).strip()]
        return ",".join(fields) if fields else None
    return str(value)


def _str_key(val: Any, field: str) -> str:
    """Coerce an issue key or ID to string (LLMs sometimes pass integers)."""
    if val is None:
        raise KeyError(field)
    return str(val)


def _issue_to_dict(issue: Any) -> dict[str, Any]:
    f = issue.fields
    return {
        "key": issue.key,
        "summary": getattr(f, "summary", None),
        "status": str(getattr(f, "status", None)),
        "issue_type": str(getattr(f, "issuetype", None)),
        "priority": str(getattr(f, "priority", None)),
        "assignee": str(getattr(f, "assignee", None)),
        "reporter": str(getattr(f, "reporter", None)),
        "created": str(getattr(f, "created", None)),
        "updated": str(getattr(f, "updated", None)),
        "description": getattr(f, "description", None),
        "labels": getattr(f, "labels", []),
        "components": [str(c) for c in getattr(f, "components", [])],
        "fix_versions": [str(v) for v in getattr(f, "fixVersions", [])],
    }


@tool(gatherable=True, summary=_field_summary("jql"), health_check=health)
async def jira_search(
    jql: str,
    max_results: int = 50,
    fields: list[str] | str | None = None,
) -> str:
    """Search Jira issues with JQL."""
    _, jira = _credentials_and_client()
    try:
        if not jql:
            raise ToolError("missing required arg 'jql'.")
        fields_str = _normalize_fields(fields)
        issues = jira.search_issues(jql, maxResults=int(max_results), fields=fields_str)
        result = [_issue_to_dict(i) for i in issues]
        return _fmt({"total": len(result), "issues": result})
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("issue_key"), health_check=health)
async def jira_get(issue_key: str) -> str:
    """Fetch one Jira issue by key, e.g. PROJ-123."""
    _, jira = _credentials_and_client()
    try:
        issue = jira.issue(_str_key(issue_key, "issue_key"))
        return _fmt(_issue_to_dict(issue))
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("issue_key"), health_check=health)
async def jira_get_transitions(issue_key: str) -> str:
    """List available transitions for a Jira issue."""
    _, jira = _credentials_and_client()
    try:
        transitions = jira.transitions(_str_key(issue_key, "issue_key"))
        return _fmt([{"id": t["id"], "name": t["name"]} for t in transitions])
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(gatherable=True, health_check=health)
async def jira_get_projects() -> str:
    """List Jira projects."""
    _, jira = _credentials_and_client()
    try:
        projects = jira.projects()
        return _fmt([{"key": p.key, "name": p.name} for p in projects])
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("issue_key"), health_check=health)
async def jira_get_comments(issue_key: str) -> str:
    """List comments on a Jira issue."""
    _, jira = _credentials_and_client()
    try:
        comments = jira.comments(_str_key(issue_key, "issue_key"))
        return _fmt(
            [
                {
                    "id": c.id,
                    "author": str(c.author),
                    "created": str(c.created),
                    "body": c.body,
                }
                for c in comments
            ]
        )
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("issue_key"), health_check=health)
async def jira_get_attachments(issue_key: str) -> str:
    """List attachments on a Jira issue."""
    _, jira = _credentials_and_client()
    try:
        issue = jira.issue(_str_key(issue_key, "issue_key"), fields="attachment")
        attachments = getattr(issue.fields, "attachment", []) or []
        return _fmt(
            [
                {
                    "id": a.id,
                    "filename": a.filename,
                    "size": a.size,
                    "mime_type": a.mimeType,
                    "created": str(a.created),
                    "author": str(a.author),
                    "content_url": a.content,
                }
                for a in attachments
            ]
        )
    except Exception as exc:
        raise _jira_error(exc) from exc


@tool(summary=_field_summary("attachment_id"), health_check=health)
async def jira_download_attachment(attachment_id: str | int, save_path: str | None = None) -> str:
    """Download a Jira attachment by attachment id."""
    creds, jira = _credentials_and_client()
    try:
        attachment = jira.attachment(_str_key(attachment_id, "attachment_id"))
        filename = attachment.filename
        if save_path:
            dest = Path(save_path)
        else:
            from aiyo.config import settings

            dest = Path(settings.work_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(auth=creds.http_auth(), follow_redirects=True) as client:
            resp = client.get(attachment.content)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return _fmt({"saved_to": str(dest), "size": len(resp.content), "filename": filename})
    except Exception as exc:
        raise _jira_error(exc) from exc
