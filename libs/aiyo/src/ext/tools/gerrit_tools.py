"""Gerrit tool: a single CLI-style interface for all Gerrit operations.

Auth is read from environment variables (or .env file):
  GERRIT_SERVER   — Gerrit instance URL (e.g., https://gerrit.example.com/)
  GERRIT_USERNAME — username (lowercase)
  GERRIT_PASSWORD — HTTP password (generate in Gerrit → Settings → HTTP Credentials)

Auth mechanism: HTTP Digest auth (some servers require Digest, not Basic).

All requests go to the authenticated REST endpoint (/a/...).
Gerrit REST responses are prefixed with ``)]}'\\n`` which is stripped automatically.
"""

import json
from typing import Any
from urllib.parse import quote

import httpx
from aiyo.tools.exceptions import ToolError

from ext.config import ExtSettings

_GERRIT_MAGIC = b")]}'\n"

# Fields requested by default for change queries.
# Passed as repeated ?o=X&o=Y params (httpx list syntax).
_CHANGE_OPTIONS = [
    "DETAILED_ACCOUNTS",
    "DETAILED_LABELS",
    "MESSAGES",
    "CURRENT_REVISION",
    "CURRENT_COMMIT",
]


def health() -> dict[str, Any]:
    """Check Gerrit connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.gerrit_server:
        return {
            "name": "gerrit_cli",
            "status": "not_configured",
            "message": "GERRIT_SERVER missing",
        }
    if not cfg.gerrit_username:
        return {
            "name": "gerrit_cli",
            "status": "not_configured",
            "message": "GERRIT_USERNAME missing",
        }
    if not cfg.gerrit_password:
        return {
            "name": "gerrit_cli",
            "status": "not_configured",
            "message": "GERRIT_PASSWORD missing",
        }

    try:
        server = cfg.gerrit_server.rstrip("/")
        auth = httpx.DigestAuth(cfg.gerrit_username, cfg.gerrit_password)
        with httpx.Client(auth=auth, follow_redirects=True, timeout=10) as client:
            resp = client.get(f"{server}/a/config/server/version")
            resp.raise_for_status()
        return {"name": "gerrit_cli", "status": "ok", "message": server}
    except Exception as e:
        return {"name": "gerrit_cli", "status": "error", "message": str(e)}


class GerritCredentials:
    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.gerrit_server.rstrip("/")
        self.username = cfg.gerrit_username
        self.password = cfg.gerrit_password
        if not self.username:
            raise KeyError("GERRIT_USERNAME")
        if not self.password:
            raise KeyError("GERRIT_PASSWORD")

    def auth(self) -> httpx.DigestAuth:
        return httpx.DigestAuth(self.username, self.password)

    def base_url(self) -> str:
        return f"{self.server}/a"


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _str_change_id(val: Any, field: str = "change_id") -> str:
    """Coerce change_id to string. Accepts integer change numbers or full change IDs."""
    if val is None:
        raise KeyError(field)
    return str(val)


def _parse(response: httpx.Response) -> Any:
    """Strip Gerrit magic prefix and parse JSON."""
    content = response.content
    if content.startswith(_GERRIT_MAGIC):
        content = content[len(_GERRIT_MAGIC) :]
    return json.loads(content)


def _encode_project(project: str) -> str:
    """Gerrit requires project names to be percent-encoded."""
    return quote(project, safe="")


async def gerrit_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute a Gerrit operation.

    Auth is read from env vars: GERRIT_SERVER, GERRIT_USERNAME, GERRIT_PASSWORD
    (HTTP password from Gerrit → Settings → HTTP Credentials, NOT your login password).

    IMPORTANT — change_id: accepts either the numeric change number (e.g. 448402) or the
    full change ID string (e.g. "myproject~main~I8473b95934b5732ac55d26311a706c9c2bde9940").
    Using the numeric change number is simpler and always works. Integers are accepted.

    IMPORTANT — edit vs publish: edit_commit_message and edit_file_content stage a "change
    edit" (a draft patch set). By default they also publish it immediately (publish=true).
    Set publish=false to stage multiple edits, then call publish_edit once when done.

    IMPORTANT — commit messages: must end with a blank line followed by the Change-Id footer,
    e.g. "Fix bug\\n\\nChange-Id: I8473b95934b5732ac55d26311a706c9c2bde9940\\n".
    Omitting the Change-Id will cause the push to be rejected.

    Supported commands
    ──────────────────

    "list_changes"
        Query changes using Gerrit query syntax.
        Optional : query (str, default "status:open") — e.g. "project:kernel status:open owner:me"
                   limit (int, default 25) — max changes to return
        Returns  : [{id, change_number, project, branch, subject, status, owner, created,
                   updated, insertions, deletions, topic, hashtags, labels, commit}]

    "get_change"
        Get basic info for a single change.
        Required : change_id (str | int) — numeric change number or full change ID
        Returns  : same shape as list_changes items

    "get_change_detail"
        Get detailed info including file list, commit, labels, and messages.
        Required : change_id (str | int)
        Returns  : same as get_change plus files: {path: {lines_inserted, lines_deleted, size_delta, status}}

    "get_change_diff"
        Get unified diff content for all modified files in a change (capped at 20 files).
        Required : change_id (str | int)
        Optional : revision (str, default "current") — patch set number or "current"
                   base_revision (str | null) — base patch set to diff against; omit for diff vs parent
        Returns  : {file_path: <Gerrit diff object>}

    "get_change_messages"
        Get all review/comment messages on a change in chronological order.
        Required : change_id (str | int)
        Returns  : [{id, author, date, message, patch_set}]

    "set_review"
        Post a review message and/or label votes on the current patch set.
        Required : change_id (str | int)
                   message (str) — review comment text (can be empty string "")
        Optional : code_review (int) — Code-Review vote: -2, -1, 0, +1, or +2
                   verified (int)    — Verified vote: -1, 0, or +1
        Returns  : Gerrit ReviewResult object

    "abandon_change"
        Abandon (close without merging) a change.
        Required : change_id (str | int)
        Optional : message (str) — reason for abandoning
        Returns  : {status, change_id}

    "rebase_change"
        Rebase a change onto the current tip of its target branch.
        Required : change_id (str | int)
        Returns  : updated change dict

    "cherry_pick"
        Cherry-pick the current patch set of a change to another branch.
        Required : change_id (str | int)
                   destination_branch (str) — target branch name, e.g. "stable-5.15"
        Optional : message (str) — override commit message for the cherry-pick
        Returns  : new change dict for the cherry-picked change

    "edit_commit_message"
        Update the commit message of a change (creates/updates a change edit).
        Required : change_id (str | int)
                   message (str) — full commit message including Change-Id footer
        Optional : publish (bool, default true) — publish the edit immediately as a new patch set
        Returns  : confirmation string

    "edit_file_content"
        Replace the content of a file in a change edit.
        Required : change_id (str | int)
                   file_path (str) — repo-relative path, e.g. "drivers/foo/bar.c"
                   content (str)   — full new file content (text)
        Optional : publish (bool, default true) — publish the edit immediately as a new patch set
        Returns  : confirmation string

    "publish_edit"
        Publish the pending change edit as a new patch set (use after edit_file_content/
        edit_commit_message with publish=false).
        Required : change_id (str | int)
        Returns  : confirmation string

    "delete_edit"
        Discard the pending change edit without publishing.
        Required : change_id (str | int)
        Returns  : confirmation string

    "get_file_content"
        Get the content of a file at a specific revision (returned as decoded text).
        Required : change_id (str | int)
                   file_path (str) — repo-relative path
        Optional : revision (str, default "current") — patch set number or "current"
        Returns  : {file_path, content}

    "list_projects"
        List accessible Gerrit projects.
        Optional : prefix (str) — filter projects whose name starts with this prefix
                   limit (int, default 100) — max projects to return
        Returns  : [{name, state, id}]

    "get_project_branches"
        List branches for a Gerrit project.
        Required : project (str) — project name, e.g. "platform/kernel"
        Optional : limit (int, default 50)
        Returns  : [{ref, revision, can_delete}]

    Args:
        command: The operation to perform (see list above).
        args: Parameters for the operation as a dict.
    """
    if args is None:
        args = {}

    try:
        creds = GerritCredentials()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Gerrit credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  GERRIT_SERVER=https://your-gerrit.example.com\n"
            "  GERRIT_USERNAME=your-username\n"
            "  GERRIT_PASSWORD=your-http-password\n"
        )

    base = creds.base_url()
    auth = creds.auth()

    try:
        with httpx.Client(auth=auth, follow_redirects=True, timeout=30) as client:
            if command == "list_changes":
                query = args.get("query", "status:open")
                limit = int(args.get("limit", 25))
                resp = client.get(
                    f"{base}/changes/",
                    params={"q": query, "n": limit, "o": _CHANGE_OPTIONS},
                )
                resp.raise_for_status()
                changes = _parse(resp)
                return _fmt([_change_to_dict(c) for c in changes])

            elif command == "get_change":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.get(
                    f"{base}/changes/{change_id}",
                    params={"o": _CHANGE_OPTIONS},
                )
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "get_change_detail":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.get(
                    f"{base}/changes/{change_id}/detail",
                    params={"o": _CHANGE_OPTIONS},
                )
                resp.raise_for_status()
                change = _parse(resp)
                # Also fetch file list for the current revision
                current_rev = _current_revision(change)
                files: dict[str, Any] = {}
                if current_rev:
                    fr = client.get(f"{base}/changes/{change_id}/revisions/{current_rev}/files")
                    if fr.is_success:
                        raw_files = _parse(fr)
                        files = {
                            path: {
                                "lines_inserted": info.get("lines_inserted", 0),
                                "lines_deleted": info.get("lines_deleted", 0),
                                "size_delta": info.get("size_delta", 0),
                                "status": info.get("status"),
                            }
                            for path, info in raw_files.items()
                        }
                result = _change_to_dict(change)
                result["files"] = files
                return _fmt(result)

            elif command == "get_change_diff":
                change_id = _str_change_id(args.get("change_id"))
                revision = args.get("revision", "current")
                base_rev = args.get("base_revision")
                # Get file list first
                fr = client.get(f"{base}/changes/{change_id}/revisions/{revision}/files")
                fr.raise_for_status()
                file_list = [p for p in _parse(fr) if p != "/COMMIT_MSG"]
                diffs: dict[str, Any] = {}
                diff_params: dict[str, Any] = {}
                if base_rev:
                    diff_params["base"] = base_rev
                for file_path in file_list[:20]:  # cap at 20 files to avoid huge output
                    enc_path = quote(file_path, safe="")
                    dr = client.get(
                        f"{base}/changes/{change_id}/revisions/{revision}/files/{enc_path}/diff",
                        params=diff_params,
                    )
                    if dr.is_success:
                        diffs[file_path] = _parse(dr)
                return _fmt(diffs)

            elif command == "get_change_messages":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.get(f"{base}/changes/{change_id}/messages")
                resp.raise_for_status()
                messages = _parse(resp)
                return _fmt(
                    [
                        {
                            "id": m.get("id"),
                            "author": m.get("author", {}).get("name"),
                            "date": m.get("date"),
                            "message": m.get("message"),
                            "patch_set": m.get("_revision_number"),
                        }
                        for m in messages
                    ]
                )

            elif command == "set_review":
                change_id = _str_change_id(args.get("change_id"))
                if "message" not in args:
                    raise ToolError(
                        "missing required arg 'message' for command 'set_review'. "
                        "Pass an empty string \"\" for no message."
                    )
                body: dict[str, Any] = {"message": args["message"]}
                labels: dict[str, int] = {}
                if "code_review" in args:
                    labels["Code-Review"] = int(args["code_review"])
                if "verified" in args:
                    labels["Verified"] = int(args["verified"])
                if labels:
                    body["labels"] = labels
                resp = client.post(
                    f"{base}/changes/{change_id}/revisions/current/review",
                    json=body,
                )
                resp.raise_for_status()
                return _fmt(_parse(resp))

            elif command == "abandon_change":
                change_id = _str_change_id(args.get("change_id"))
                body = {}
                if "message" in args:
                    body["message"] = args["message"]
                resp = client.post(f"{base}/changes/{change_id}/abandon", json=body)
                resp.raise_for_status()
                change = _parse(resp)
                return _fmt({"status": change.get("status"), "change_id": change.get("id")})

            elif command == "rebase_change":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.post(f"{base}/changes/{change_id}/rebase", json={})
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "cherry_pick":
                change_id = _str_change_id(args.get("change_id"))
                destination = args.get("destination_branch")
                if not destination:
                    raise ToolError(
                        "missing required arg 'destination_branch' for command 'cherry_pick'."
                    )
                body = {"destination": destination}
                if "message" in args:
                    body["message"] = args["message"]
                resp = client.post(
                    f"{base}/changes/{change_id}/revisions/current/cherrypick",
                    json=body,
                )
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "edit_commit_message":
                change_id = _str_change_id(args.get("change_id"))
                message = args.get("message")
                if message is None:
                    raise ToolError(
                        "missing required arg 'message' for command 'edit_commit_message'. "
                        "Must include the full commit message with Change-Id footer."
                    )
                resp = client.put(
                    f"{base}/changes/{change_id}/edit:message",
                    json={"message": message},
                )
                # 204 No Content on success
                if resp.status_code not in (200, 204):
                    resp.raise_for_status()
                publish = args.get("publish", True)
                if publish:
                    pr = client.post(f"{base}/changes/{change_id}/edit:publish", json={})
                    pr.raise_for_status()
                    return f"Commit message updated and published for {change_id}."
                return f"Commit message staged for {change_id} (not yet published)."

            elif command == "edit_file_content":
                change_id = _str_change_id(args.get("change_id"))
                file_path = args.get("file_path")
                content = args.get("content")
                if not file_path:
                    raise ToolError(
                        "missing required arg 'file_path' for command 'edit_file_content'."
                    )
                if content is None:
                    raise ToolError(
                        "missing required arg 'content' for command 'edit_file_content'."
                    )
                enc_path = quote(file_path, safe="")
                resp = client.put(
                    f"{base}/changes/{change_id}/edit/{enc_path}",
                    content=str(content).encode(),
                    headers={"Content-Type": "text/plain"},
                )
                if resp.status_code not in (200, 204):
                    resp.raise_for_status()
                publish = args.get("publish", True)
                if publish:
                    pr = client.post(f"{base}/changes/{change_id}/edit:publish", json={})
                    pr.raise_for_status()
                    return f"File '{file_path}' updated and published for {change_id}."
                return f"File '{file_path}' staged for {change_id} (not yet published)."

            elif command == "publish_edit":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.post(f"{base}/changes/{change_id}/edit:publish", json={})
                resp.raise_for_status()
                return f"Edit published as new patch set for {change_id}."

            elif command == "delete_edit":
                change_id = _str_change_id(args.get("change_id"))
                resp = client.delete(f"{base}/changes/{change_id}/edit")
                if resp.status_code not in (200, 204):
                    resp.raise_for_status()
                return f"Edit deleted for {change_id}."

            elif command == "get_file_content":
                change_id = _str_change_id(args.get("change_id"))
                file_path = args.get("file_path")
                if not file_path:
                    raise ToolError(
                        "missing required arg 'file_path' for command 'get_file_content'."
                    )
                revision = args.get("revision", "current")
                enc_path = quote(file_path, safe="")
                resp = client.get(
                    f"{base}/changes/{change_id}/revisions/{revision}/files/{enc_path}/content"
                )
                resp.raise_for_status()
                # Response is base64-encoded
                import base64

                decoded = base64.b64decode(resp.content).decode("utf-8", errors="replace")
                return _fmt({"file_path": file_path, "content": decoded})

            elif command == "list_projects":
                list_params: dict[str, Any] = {}
                if "prefix" in args:
                    list_params["p"] = args["prefix"]
                list_params["n"] = int(args.get("limit", 100))
                resp = client.get(f"{base}/projects/", params=list_params)
                resp.raise_for_status()
                projects = _parse(resp)
                return _fmt(
                    [
                        {"name": name, "state": info.get("state"), "id": info.get("id")}
                        for name, info in projects.items()
                    ]
                )

            elif command == "get_project_branches":
                project = args.get("project")
                if not project:
                    raise ToolError(
                        "missing required arg 'project' for command 'get_project_branches'."
                    )
                limit = int(args.get("limit", 50))
                enc_project = _encode_project(project)
                resp = client.get(
                    f"{base}/projects/{enc_project}/branches",
                    params={"n": limit},
                )
                resp.raise_for_status()
                branches = _parse(resp)
                return _fmt(
                    [
                        {
                            "ref": b.get("ref"),
                            "revision": b.get("revision"),
                            "can_delete": b.get("can_delete"),
                        }
                        for b in branches
                    ]
                )

            else:
                raise ToolError(
                    f"Unknown command '{command}'. "
                    "Valid commands: list_changes, get_change, get_change_detail, "
                    "get_change_diff, get_change_messages, set_review, abandon_change, "
                    "rebase_change, cherry_pick, edit_commit_message, edit_file_content, "
                    "publish_edit, delete_edit, get_file_content, list_projects, "
                    "get_project_branches."
                )

    except httpx.HTTPStatusError as e:
        raise ToolError(f"Gerrit HTTP {e.response.status_code}: {e.response.text[:500]}") from e
    except KeyError as e:
        raise ToolError(f"Missing required arg {e} for command '{command}'.") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e)) from e


def _current_revision(change: dict[str, Any]) -> str | None:
    return change.get("current_revision")


def _change_to_dict(change: dict[str, Any]) -> dict[str, Any]:
    current_rev = change.get("current_revision")
    commit_info: dict[str, Any] = {}
    if current_rev and "revisions" in change:
        rev_data = change["revisions"].get(current_rev, {})
        commit = rev_data.get("commit", {})
        commit_info = {
            "subject": commit.get("subject"),
            "message": commit.get("message"),
            "author": commit.get("author", {}).get("name"),
            "committer": commit.get("committer", {}).get("name"),
            "patch_set": rev_data.get("_number"),
            "ref": rev_data.get("ref"),
        }
    labels: dict[str, Any] = {}
    for label_name, label_data in change.get("labels", {}).items():
        approved = label_data.get("approved", {}).get("name")
        rejected = label_data.get("rejected", {}).get("name")
        labels[label_name] = {"approved_by": approved, "rejected_by": rejected}
    return {
        "id": change.get("id"),
        "change_number": change.get("_number"),
        "project": change.get("project"),
        "branch": change.get("branch"),
        "subject": change.get("subject"),
        "status": change.get("status"),
        "owner": change.get("owner", {}).get("name"),
        "created": change.get("created"),
        "updated": change.get("updated"),
        "insertions": change.get("insertions"),
        "deletions": change.get("deletions"),
        "topic": change.get("topic"),
        "hashtags": change.get("hashtags"),
        "labels": labels,
        "commit": commit_info,
    }
