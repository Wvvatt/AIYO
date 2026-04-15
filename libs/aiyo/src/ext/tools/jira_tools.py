"""Jira tool: a single CLI-style interface for all Jira operations.

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


def health() -> dict[str, Any]:
    """Check Jira connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.jira_server:
        return {"name": "jira_cli", "status": "not_configured", "message": "JIRA_SERVER missing"}
    if not cfg.jira_username:
        return {"name": "jira_cli", "status": "not_configured", "message": "JIRA_USERNAME missing"}
    if not cfg.jira_password:
        return {"name": "jira_cli", "status": "not_configured", "message": "JIRA_PASSWORD missing"}

    # Try to connect
    try:
        client = JIRA(server=cfg.jira_server, basic_auth=(cfg.jira_username, cfg.jira_password))
        client.myself()
        return {"name": "jira_cli", "status": "ok", "message": cfg.jira_server}
    except Exception as e:
        return {"name": "jira_cli", "status": "error", "message": str(e)}


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


def _summary_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    raw = tool_args.get("args") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _jira_summary(tool_args: dict[str, Any]) -> str:
    cmd = tool_args.get("command", "")
    issue_key = _summary_args(tool_args).get("issue_key", "")
    return f"{cmd} {issue_key}".strip() if issue_key else cmd


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


@tool(summary=_jira_summary, health_check=health)
async def jira_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute a Jira operation.

    Auth is read from env vars: JIRA_SERVER, JIRA_USERNAME, JIRA_PASSWORD.

    IMPORTANT — issue keys: always use the full "PROJECT-123" format (e.g. "AIYO-42"),
    never just the numeric part. Keys are case-insensitive but uppercase is conventional.

    IMPORTANT — "update" fields format: values must match the Jira field schema exactly.
    Use {"name": "value"} objects for fields like priority, status, issuetype, assignee.
    Use plain strings for "summary" and "description". Examples:
      {"summary": "new title"}
      {"priority": {"name": "Minor"}}
      {"assignee": {"name": "jsmith"}}
    Do NOT pass {"priority": "Minor"} — that will fail.

    Supported commands
    ──────────────────

    "search"
        JQL search for issues.
        Required : jql (str) — JQL query, e.g. 'project = FOO AND status = "In Progress"'
        Optional : max_results (int, default 50) — max issues to return
                   fields (list[str]) — field names to include, e.g. ["summary","status","assignee"]
                   (omit fields to return all standard fields)
        Returns  : {total, issues: [{key, summary, status, issue_type, priority, assignee,
                   reporter, created, updated, description, labels, components, fix_versions}]}

    "get"
        Fetch a single issue by key with all standard fields.
        Required : issue_key (str) — e.g. "PROJ-123"
        Returns  : {key, summary, status, issue_type, priority, assignee, reporter, created,
                   updated, description, labels, components, fix_versions}

    "create"
        Create a new issue.
        Required : project (str)   — project key, e.g. "PROJ"
                   summary (str)   — issue title
        Optional : issue_type (str, default "Task") — e.g. "Bug", "Task", "Story", "Epic"
                   description (str) — plain text or Jira wiki markup
                   priority (str)  — e.g. "Blocker", "Critical", "Major", "Minor", "Trivial"
                   assignee (str)  — username/login (not display name)
                   labels (list[str]) — label strings, e.g. ["ci", "regression"]
                   components (list[str]) — component names, e.g. ["Backend", "Auth"]
        Returns  : {created (key), url}

    "update"
        Update one or more fields on an existing issue.
        Required : issue_key (str)
                   fields (dict)  — Jira field map using native schema (see IMPORTANT note above)
        Returns  : "Updated PROJ-123."

    "comment"
        Add a plain-text (wiki markup) comment to an issue.
        Required : issue_key (str)
                   body (str) — comment text (Jira wiki markup, not HTML)
        Returns  : {comment_id, created}

    "get_transitions"
        List available workflow transitions for an issue (use before calling "transition").
        Required : issue_key (str)
        Returns  : [{id, name}]

    "transition"
        Move an issue to a new workflow status. Use get_transitions first to get valid names/IDs.
        Required : issue_key (str)
                   transition (str) — transition name (e.g. "In Progress") or numeric id
        Returns  : "Transitioned PROJ-123 to 'In Progress'."

    "assign"
        Assign an issue to a user, or unassign it.
        Required : issue_key (str)
                   assignee (str | null) — username to assign, or null/None to unassign
        Returns  : "Assigned PROJ-123 to jsmith." or "Unassigned PROJ-123."

    "get_projects"
        List all Jira projects accessible to the authenticated user.
        Returns  : [{key, name}]

    "get_comments"
        Get all comments on an issue.
        Required : issue_key (str)
        Returns  : [{id, author, created, body}]

    "get_attachments"
        List all attachments on an issue.
        Required : issue_key (str)
        Returns  : [{id, filename, size, mime_type, created, author, content_url}]

    "download_attachment"
        Download an attachment by ID. Use get_attachments first to find the attachment id.
        Required : attachment_id (str | int) — numeric attachment ID from get_attachments
        Optional : save_path (str) — absolute path to save the file; defaults to WORK_DIR/<filename>
        Returns  : {saved_to, size, filename}

    Args:
        command: The operation to perform (see list above).
        args: Parameters for the operation as a dict.
    """
    if args is None:
        args = {}

    try:
        creds = JiraCredentials()
        jira = creds.client()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Jira credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  JIRA_SERVER=https://your-jira.example.com\n"
            "  JIRA_USERNAME=your-username\n"
            "  JIRA_PASSWORD=your-password-or-api-token\n"
        )

    try:
        if command == "search":
            jql = args.get("jql")
            if not jql:
                raise ToolError("missing required arg 'jql' for command 'search'.")
            max_results = int(args.get("max_results", 50))
            fields_arg = args.get("fields")
            fields_str: str | None = ",".join(fields_arg) if fields_arg else None
            issues = jira.search_issues(jql, maxResults=max_results, fields=fields_str)
            result = [_issue_to_dict(i) for i in issues]
            return _fmt({"total": len(result), "issues": result})

        elif command == "get":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            issue = jira.issue(issue_key)
            return _fmt(_issue_to_dict(issue))

        elif command == "create":
            project = args.get("project")
            summary = args.get("summary")
            if not project:
                raise ToolError("missing required arg 'project' for command 'create'.")
            if not summary:
                raise ToolError("missing required arg 'summary' for command 'create'.")
            issue_type = args.get("issue_type", "Task")
            fields: dict[str, Any] = {
                "project": {"key": str(project).upper()},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
            if "description" in args:
                fields["description"] = args["description"]
            if "priority" in args:
                p = args["priority"]
                # Accept both "Major" and {"name": "Major"}
                fields["priority"] = p if isinstance(p, dict) else {"name": p}
            if "assignee" in args:
                a = args["assignee"]
                fields["assignee"] = a if isinstance(a, dict) else {"name": a}
            if "labels" in args:
                fields["labels"] = args["labels"]
            if "components" in args:
                fields["components"] = [{"name": c} for c in args["components"]]
            issue = jira.create_issue(fields=fields)
            return _fmt({"created": issue.key, "url": issue.permalink()})

        elif command == "update":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            update_fields = args.get("fields")
            if update_fields is None:
                raise ToolError(
                    "missing required arg 'fields' for command 'update'. "
                    "Pass a dict of Jira field names to values, e.g. "
                    '{"summary": "new title"} or {"priority": {"name": "Minor"}}.'
                )
            if not isinstance(update_fields, dict):
                raise ToolError(
                    f"'fields' must be a dict, not {type(update_fields).__name__}. "
                    'Example: {"summary": "new title", "priority": {"name": "Minor"}}'
                )
            issue = jira.issue(issue_key)
            issue.update(fields=update_fields)
            return f"Updated {issue_key}."

        elif command == "comment":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            body = args.get("body")
            if body is None:
                raise ToolError("missing required arg 'body' for command 'comment'.")
            comment = jira.add_comment(issue_key, str(body))
            return _fmt({"comment_id": comment.id, "created": str(comment.created)})

        elif command == "get_transitions":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            transitions = jira.transitions(issue_key)
            return _fmt([{"id": t["id"], "name": t["name"]} for t in transitions])

        elif command == "transition":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            transition = args.get("transition")
            if transition is None:
                raise ToolError(
                    "missing required arg 'transition' for command 'transition'. "
                    "Use get_transitions to list valid transition names/IDs first."
                )
            jira.transition_issue(issue_key, str(transition))
            return f"Transitioned {issue_key} to '{transition}'."

        elif command == "assign":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            assignee = args.get("assignee")  # None means unassign
            if "assignee" not in args:
                raise ToolError(
                    "missing required arg 'assignee' for command 'assign'. "
                    "Pass a username string to assign, or null to unassign."
                )
            jira.assign_issue(issue_key, assignee)
            if assignee:
                return f"Assigned {issue_key} to {assignee}."
            return f"Unassigned {issue_key}."

        elif command == "get_projects":
            projects = jira.projects()
            return _fmt([{"key": p.key, "name": p.name} for p in projects])

        elif command == "get_comments":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            comments = jira.comments(issue_key)
            result = [
                {
                    "id": c.id,
                    "author": str(c.author),
                    "created": str(c.created),
                    "body": c.body,
                }
                for c in comments
            ]
            return _fmt(result)

        elif command == "get_attachments":
            issue_key = _str_key(args.get("issue_key"), "issue_key")
            issue = jira.issue(issue_key, fields="attachment")
            attachments = getattr(issue.fields, "attachment", []) or []
            result = [
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
            return _fmt(result)

        elif command == "download_attachment":
            attachment_id = _str_key(args.get("attachment_id"), "attachment_id")
            attachment = jira.attachment(attachment_id)
            filename = attachment.filename
            save_path = args.get("save_path")
            if save_path:
                dest = Path(save_path)
            else:
                from aiyo.config import settings

                dest = Path(settings.work_dir) / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = attachment.content
            with httpx.Client(auth=creds.http_auth(), follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return _fmt({"saved_to": str(dest), "size": len(resp.content), "filename": filename})

        else:
            raise ToolError(
                f"Unknown command '{command}'. "
                "Valid commands: search, get, create, update, comment, "
                "get_transitions, transition, assign, get_projects, get_comments, "
                "get_attachments, download_attachment."
            )

    except JIRAError as e:
        raise ToolError(f"Jira error {e.status_code}: {e.text}") from e
    except KeyError as e:
        raise ToolError(f"Missing required arg {e} for command '{command}'.") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e)) from e
