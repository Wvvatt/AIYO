"""Jira tool: a single CLI-style interface for all Jira operations.

Auth is read from environment variables (or .env file):
  JIRA_SERVER   — Jira instance URL (default: https://jira.amlogic.com/)
  JIRA_USERNAME — username or email
  JIRA_PASSWORD — password or API token
"""

import json
from pathlib import Path
from typing import Any

import httpx
from jira import JIRA, JIRAError

from aml.config import AmlSettings


class JiraCredentials:
    def __init__(self) -> None:
        cfg = AmlSettings()
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


async def jira_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute a Jira operation. Auth is configured via JIRA_SERVER / JIRA_USERNAME / JIRA_PASSWORD env vars.

    Supported commands and their args:

    - "search"         — JQL search.
        args: {"jql": "project=FOO AND status=Open", "max_results": 50, "fields": ["summary","status"]}
    - "get"            — Fetch a single issue.
        args: {"issue_key": "PROJ-123"}
    - "create"         — Create a new issue.
        args: {"project": "PROJ", "summary": "...", "issue_type": "Bug",
                "description": "...", "priority": "Major", "assignee": "username",
                "labels": ["label1"], "components": ["ComponentA"]}
    - "update"         — Update fields on an existing issue.
        args: {"issue_key": "PROJ-123", "fields": {"summary": "new title", "priority": {"name": "Minor"}}}
    - "comment"        — Add a comment to an issue.
        args: {"issue_key": "PROJ-123", "body": "comment text"}
    - "get_transitions" — List available workflow transitions for an issue.
        args: {"issue_key": "PROJ-123"}
    - "transition"     — Move an issue to a new status by transition name or id.
        args: {"issue_key": "PROJ-123", "transition": "In Progress"}
    - "assign"         — Assign an issue to a user (use null/None to unassign).
        args: {"issue_key": "PROJ-123", "assignee": "username"}
    - "get_projects"   — List accessible Jira projects.
        args: {}
    - "get_comments"   — Get all comments on an issue.
        args: {"issue_key": "PROJ-123"}
    - "get_attachments" — List all attachments on an issue.
        args: {"issue_key": "PROJ-123"}
    - "download_attachment" — Download an attachment to a local path.
        args: {"attachment_id": "12345", "save_path": "/tmp/file.txt"}
        If save_path is omitted, saves to WORK_DIR/<filename>.

    Args:
        command: The operation to perform (see list above).
        args: Parameters for the operation as a dict.
    """
    if args is None:
        args = {}
    elif isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return f"Error: args is not valid JSON — {args!r}"

    try:
        creds = JiraCredentials()
        jira = creds.client()
    except KeyError as e:
        return f"Error: missing environment variable {e}. Set JIRA_USERNAME and JIRA_PASSWORD."

    try:
        if command == "search":
            jql = args.get("jql", "")
            max_results = int(args.get("max_results", 50))
            fields_arg = args.get("fields")
            fields = ",".join(fields_arg) if fields_arg else None
            issues = jira.search_issues(jql, maxResults=max_results, fields=fields)
            result = [_issue_to_dict(i) for i in issues]
            return _fmt({"total": len(result), "issues": result})

        elif command == "get":
            issue_key = args["issue_key"]
            issue = jira.issue(issue_key)
            return _fmt(_issue_to_dict(issue))

        elif command == "create":
            project = args["project"]
            summary = args["summary"]
            issue_type = args.get("issue_type", "Task")
            fields: dict[str, Any] = {
                "project": {"key": project},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
            if "description" in args:
                fields["description"] = args["description"]
            if "priority" in args:
                fields["priority"] = {"name": args["priority"]}
            if "assignee" in args:
                fields["assignee"] = {"name": args["assignee"]}
            if "labels" in args:
                fields["labels"] = args["labels"]
            if "components" in args:
                fields["components"] = [{"name": c} for c in args["components"]]
            issue = jira.create_issue(fields=fields)
            return _fmt({"created": issue.key, "url": issue.permalink()})

        elif command == "update":
            issue_key = args["issue_key"]
            update_fields = args["fields"]
            issue = jira.issue(issue_key)
            issue.update(fields=update_fields)
            return f"Updated {issue_key}."

        elif command == "comment":
            issue_key = args["issue_key"]
            body = args["body"]
            comment = jira.add_comment(issue_key, body)
            return _fmt({"comment_id": comment.id, "created": str(comment.created)})

        elif command == "get_transitions":
            issue_key = args["issue_key"]
            transitions = jira.transitions(issue_key)
            return _fmt([{"id": t["id"], "name": t["name"]} for t in transitions])

        elif command == "transition":
            issue_key = args["issue_key"]
            transition = args["transition"]
            jira.transition_issue(issue_key, transition)
            return f"Transitioned {issue_key} to '{transition}'."

        elif command == "get_projects":
            projects = jira.projects()
            return _fmt([{"key": p.key, "name": p.name} for p in projects])

        elif command == "get_comments":
            issue_key = args["issue_key"]
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
            issue_key = args["issue_key"]
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
            attachment_id = args["attachment_id"]
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
            return (
                f"Unknown command '{command}'. "
                "Valid commands: search, get, create, update, comment, "
                "get_transitions, transition, assign, get_projects, get_comments, "
                "get_attachments, download_attachment."
            )

    except JIRAError as e:
        return f"Jira error {e.status_code}: {e.text}"
    except KeyError as e:
        return f"Error: missing required arg {e} for command '{command}'."
    except Exception as e:
        return f"Error: {e}"
