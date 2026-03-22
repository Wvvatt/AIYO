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


def health() -> dict:
    """Check Gerrit connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.gerrit_server:
        return {"name": "gerrit_cli", "status": "not_configured", "message": "GERRIT_SERVER missing"}
    if not cfg.gerrit_username:
        return {"name": "gerrit_cli", "status": "not_configured", "message": "GERRIT_USERNAME missing"}
    if not cfg.gerrit_password:
        return {"name": "gerrit_cli", "status": "not_configured", "message": "GERRIT_PASSWORD missing"}

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
    """Execute a Gerrit operation. Auth is configured via GERRIT_SERVER / GERRIT_USERNAME / GERRIT_PASSWORD env vars.

    Supported commands and their args:

    - "list_changes"     — Query changes.
        args: {"query": "status:open", "limit": 25}
    - "get_change"       — Get basic info for a change.
        args: {"change_id": "448402"}
    - "get_change_detail" — Get detailed info including files, commit, messages.
        args: {"change_id": "448402"}
    - "get_change_diff"  — Get file diffs for a change.
        args: {"change_id": "448402", "revision": "current", "base_revision": null}
    - "get_change_messages" — Get all review messages for a change.
        args: {"change_id": "448402"}
    - "set_review"       — Post a review comment and/or score on a change.
        args: {"change_id": "448402", "message": "LGTM",
                "code_review": 1,     # -2..+2, optional
                "verified": 1}         # -1..+1, optional
    - "abandon_change"   — Abandon a change.
        args: {"change_id": "448402", "message": "not needed"}
    - "rebase_change"    — Rebase a change onto the tip of its target branch.
        args: {"change_id": "448402"}
    - "cherry_pick"      — Cherry-pick a change to another branch.
        args: {"change_id": "448402", "destination_branch": "stable-5.15",
                "message": "optional commit message"}
    - "edit_commit_message" — Update the commit message of a change.
        args: {"change_id": "448402", "message": "new commit message\\n\\nChange-Id: I..."}
    - "edit_file_content" — Replace a file in the change edit.
        args: {"change_id": "448402", "file_path": "drivers/foo/bar.c", "content": "..."}
    - "publish_edit"     — Publish the pending change edit as a new patch set.
        args: {"change_id": "448402"}
    - "delete_edit"      — Delete (discard) the pending change edit.
        args: {"change_id": "448402"}
    - "get_file_content" — Get file content from a specific revision.
        args: {"change_id": "448402", "file_path": "drivers/foo/bar.c",
                "revision": "current"}
    - "list_projects"    — List accessible Gerrit projects.
        args: {"prefix": "kernel", "limit": 100}
    - "get_project_branches" — List branches for a project.
        args: {"project": "platform/kernel", "limit": 50}

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
            raise ToolError(f"args is not valid JSON — {args!r}")

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
                change_id = args["change_id"]
                resp = client.get(
                    f"{base}/changes/{change_id}",
                    params={"o": _CHANGE_OPTIONS},
                )
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "get_change_detail":
                change_id = args["change_id"]
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
                change_id = args["change_id"]
                revision = args.get("revision", "current")
                base_rev = args.get("base_revision")
                # Get file list first
                fr = client.get(f"{base}/changes/{change_id}/revisions/{revision}/files")
                fr.raise_for_status()
                file_list = [p for p in _parse(fr) if p != "/COMMIT_MSG"]
                diffs: dict[str, Any] = {}
                params: dict[str, Any] = {}
                if base_rev:
                    params["base"] = base_rev
                for file_path in file_list[:20]:  # cap at 20 files to avoid huge output
                    enc_path = quote(file_path, safe="")
                    dr = client.get(
                        f"{base}/changes/{change_id}/revisions/{revision}/files/{enc_path}/diff",
                        params=params,
                    )
                    if dr.is_success:
                        diffs[file_path] = _parse(dr)
                return _fmt(diffs)

            elif command == "get_change_messages":
                change_id = args["change_id"]
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
                change_id = args["change_id"]
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
                change_id = args["change_id"]
                body: dict[str, Any] = {}
                if "message" in args:
                    body["message"] = args["message"]
                resp = client.post(f"{base}/changes/{change_id}/abandon", json=body)
                resp.raise_for_status()
                change = _parse(resp)
                return _fmt({"status": change.get("status"), "change_id": change.get("id")})

            elif command == "rebase_change":
                change_id = args["change_id"]
                resp = client.post(f"{base}/changes/{change_id}/rebase", json={})
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "cherry_pick":
                change_id = args["change_id"]
                destination = args["destination_branch"]
                body: dict[str, Any] = {"destination": destination}
                if "message" in args:
                    body["message"] = args["message"]
                resp = client.post(
                    f"{base}/changes/{change_id}/revisions/current/cherrypick",
                    json=body,
                )
                resp.raise_for_status()
                return _fmt(_change_to_dict(_parse(resp)))

            elif command == "edit_commit_message":
                change_id = args["change_id"]
                message = args["message"]
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
                change_id = args["change_id"]
                file_path = args["file_path"]
                content = args["content"]
                enc_path = quote(file_path, safe="")
                resp = client.put(
                    f"{base}/changes/{change_id}/edit/{enc_path}",
                    content=content.encode(),
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
                change_id = args["change_id"]
                resp = client.post(f"{base}/changes/{change_id}/edit:publish", json={})
                resp.raise_for_status()
                return f"Edit published as new patch set for {change_id}."

            elif command == "delete_edit":
                change_id = args["change_id"]
                resp = client.delete(f"{base}/changes/{change_id}/edit")
                if resp.status_code not in (200, 204):
                    resp.raise_for_status()
                return f"Edit deleted for {change_id}."

            elif command == "get_file_content":
                change_id = args["change_id"]
                file_path = args["file_path"]
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
                params: dict[str, Any] = {}
                if "prefix" in args:
                    params["p"] = args["prefix"]
                if "limit" in args:
                    params["n"] = int(args["limit"])
                resp = client.get(f"{base}/projects/", params=params)
                resp.raise_for_status()
                projects = _parse(resp)
                return _fmt(
                    [
                        {"name": name, "state": info.get("state"), "id": info.get("id")}
                        for name, info in projects.items()
                    ]
                )

            elif command == "get_project_branches":
                project = args["project"]
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
        raise ToolError(f"missing required arg {e} for command '{command}'.") from e
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
