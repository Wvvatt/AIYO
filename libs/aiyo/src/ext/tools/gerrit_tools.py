"""Gerrit tools.

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
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError

from ext.config import ExtSettings
from ext.infra.credentials import GerritCredentials
from ext.tools._health_cache import cached_health

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


async def health() -> dict[str, Any]:
    """Check Gerrit connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    async def _probe() -> dict[str, Any]:
        cfg = ExtSettings()
        if not cfg.gerrit_server:
            return {
                "name": "gerrit",
                "status": "not_configured",
                "message": "GERRIT_SERVER missing",
            }
        if not cfg.gerrit_username:
            return {
                "name": "gerrit",
                "status": "not_configured",
                "message": "GERRIT_USERNAME missing",
            }
        if not cfg.gerrit_password:
            return {
                "name": "gerrit",
                "status": "not_configured",
                "message": "GERRIT_PASSWORD missing",
            }

        try:
            server = cfg.gerrit_server.rstrip("/")
            auth = httpx.DigestAuth(cfg.gerrit_username, cfg.gerrit_password)
            async with httpx.AsyncClient(auth=auth, follow_redirects=True, timeout=10) as client:
                resp = await client.get(f"{server}/a/config/server/version")
                resp.raise_for_status()
            return {"name": "gerrit", "status": "ok", "message": server}
        except Exception as e:
            return {"name": "gerrit", "status": "error", "message": str(e)}

    return await cached_health("gerrit", _probe)


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _credentials() -> GerritCredentials:
    try:
        return GerritCredentials()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Gerrit credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  GERRIT_SERVER=https://your-gerrit.example.com\n"
            "  GERRIT_USERNAME=your-username\n"
            "  GERRIT_PASSWORD=your-http-password\n"
        ) from e


def _gerrit_error(exc: Exception) -> ToolError:
    if isinstance(exc, httpx.HTTPStatusError):
        return ToolError(f"Gerrit HTTP {exc.response.status_code}: {exc.response.text[:500]}")
    if isinstance(exc, KeyError):
        return ToolError(f"missing required arg '{str(exc).strip(chr(39) + chr(34))}'.")
    if isinstance(exc, ToolError):
        return exc
    return ToolError(str(exc))


def _field_summary(*names: str):
    def summary(tool_args: dict[str, Any]) -> str:
        return " ".join(str(tool_args.get(name)) for name in names if tool_args.get(name))

    return summary


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


@tool(gatherable=True, summary=_field_summary("query"), health_check=health)
async def gerrit_list_changes(query: str = "status:open", limit: int = 25) -> str:
    """Query Gerrit changes."""
    creds = _credentials()
    try:
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(
                f"{creds.base_url()}/changes/",
                params={"q": query, "n": int(limit), "o": _CHANGE_OPTIONS},
            )
            resp.raise_for_status()
            changes = _parse(resp)
            return _fmt([_change_to_dict(c) for c in changes])
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("change_id"), health_check=health)
async def gerrit_get_change(change_id: str | int) -> str:
    """Get basic info for a Gerrit change."""
    creds = _credentials()
    try:
        change_id = _str_change_id(change_id)
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(f"{creds.base_url()}/changes/{change_id}", params={"o": _CHANGE_OPTIONS})
            resp.raise_for_status()
            return _fmt(_change_to_dict(_parse(resp)))
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("change_id"), health_check=health)
async def gerrit_get_change_detail(change_id: str | int) -> str:
    """Get detailed Gerrit change info including files."""
    creds = _credentials()
    try:
        change_id = _str_change_id(change_id)
        base = creds.base_url()
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(f"{base}/changes/{change_id}/detail", params={"o": _CHANGE_OPTIONS})
            resp.raise_for_status()
            change = _parse(resp)
            files: dict[str, Any] = {}
            current_rev = _current_revision(change)
            if current_rev:
                fr = client.get(f"{base}/changes/{change_id}/revisions/{current_rev}/files")
                if fr.is_success:
                    raw_files = _parse(fr)
                    if isinstance(raw_files, dict):
                        files = {
                            path: {
                                "lines_inserted": info.get("lines_inserted", 0)
                                if isinstance(info, dict)
                                else 0,
                                "lines_deleted": info.get("lines_deleted", 0)
                                if isinstance(info, dict)
                                else 0,
                                "size_delta": info.get("size_delta", 0)
                                if isinstance(info, dict)
                                else 0,
                                "status": info.get("status") if isinstance(info, dict) else None,
                            }
                            for path, info in raw_files.items()
                        }
            result = _change_to_dict(change)
            result["files"] = files
            return _fmt(result)
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("change_id"), health_check=health)
async def gerrit_get_change_diff(
    change_id: str | int,
    revision: str = "current",
    base_revision: str | None = None,
) -> str:
    """Get Gerrit diff data for a change."""
    creds = _credentials()
    try:
        change_id = _str_change_id(change_id)
        base = creds.base_url()
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            fr = client.get(f"{base}/changes/{change_id}/revisions/{revision}/files")
            fr.raise_for_status()
            parsed_files = _parse(fr)
            if not isinstance(parsed_files, dict):
                raise ToolError(
                    f"Unexpected response type: expected dict, got {type(parsed_files).__name__}"
                )
            diff_params: dict[str, Any] = {}
            if base_revision:
                diff_params["base"] = base_revision
            diffs: dict[str, Any] = {}
            for file_path in [p for p in parsed_files.keys() if p != "/COMMIT_MSG"][:20]:
                enc_path = quote(file_path, safe="")
                dr = client.get(
                    f"{base}/changes/{change_id}/revisions/{revision}/files/{enc_path}/diff",
                    params=diff_params,
                )
                if dr.is_success:
                    diffs[file_path] = _parse(dr)
            return _fmt(diffs)
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("change_id"), health_check=health)
async def gerrit_get_change_messages(change_id: str | int) -> str:
    """Get Gerrit review messages for a change."""
    creds = _credentials()
    try:
        change_id = _str_change_id(change_id)
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(f"{creds.base_url()}/changes/{change_id}/messages")
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
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("change_id", "file_path"), health_check=health)
async def gerrit_get_file_content(
    change_id: str | int,
    file_path: str,
    revision: str = "current",
) -> str:
    """Get file content from a Gerrit change revision."""
    creds = _credentials()
    try:
        change_id = _str_change_id(change_id)
        if not file_path:
            raise ToolError("missing required arg 'file_path'.")
        enc_path = quote(file_path, safe="")
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(
                f"{creds.base_url()}/changes/{change_id}/revisions/{revision}/files/{enc_path}/content"
            )
            resp.raise_for_status()
            import base64

            decoded = base64.b64decode(resp.content).decode("utf-8", errors="replace")
            return _fmt({"file_path": file_path, "content": decoded})
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("prefix"), health_check=health)
async def gerrit_list_projects(prefix: str | None = None, limit: int = 100) -> str:
    """List accessible Gerrit projects."""
    creds = _credentials()
    try:
        params: dict[str, Any] = {"n": int(limit)}
        if prefix is not None:
            params["p"] = prefix
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(f"{creds.base_url()}/projects/", params=params)
            resp.raise_for_status()
            projects = _parse(resp)
            return _fmt(
                [{"name": name, "state": info.get("state"), "id": info.get("id")} for name, info in projects.items()]
            )
    except Exception as exc:
        raise _gerrit_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("project"), health_check=health)
async def gerrit_get_project_branches(project: str, limit: int = 50) -> str:
    """List branches for a Gerrit project."""
    creds = _credentials()
    try:
        if not project:
            raise ToolError("missing required arg 'project'.")
        enc_project = _encode_project(project)
        with httpx.Client(auth=creds.auth(), follow_redirects=True, timeout=30) as client:
            resp = client.get(
                f"{creds.base_url()}/projects/{enc_project}/branches",
                params={"n": int(limit)},
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
    except Exception as exc:
        raise _gerrit_error(exc) from exc


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
