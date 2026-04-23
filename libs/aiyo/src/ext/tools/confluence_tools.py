"""Confluence tool: a single CLI-style interface for all Confluence operations.

Auth is read from environment variables (or .env file):
  CONFLUENCE_SERVER   — Confluence instance URL
  CONFLUENCE_USERNAME — username or email
  CONFLUENCE_PASSWORD — password or API token
"""

import json
from pathlib import Path
from typing import Any

import httpx
from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError
from atlassian import Confluence

from ext.config import ExtSettings


async def health() -> dict[str, Any]:
    """Check Confluence connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    cfg = ExtSettings()
    if not cfg.confluence_server:
        return {
            "name": "confluence_cli",
            "status": "not_configured",
            "message": "CONFLUENCE_SERVER missing",
        }

    has_token = bool(cfg.confluence_token)
    has_basic = bool(cfg.confluence_username and cfg.confluence_password)

    if not has_token and not has_basic:
        return {
            "name": "confluence_cli",
            "status": "not_configured",
            "message": "CONFLUENCE_TOKEN or USERNAME+PASSWORD missing",
        }

    try:
        headers = {}
        if has_token:
            auth = None
            headers["Authorization"] = f"Bearer {cfg.confluence_token}"
        else:
            auth = (cfg.confluence_username, cfg.confluence_password)
        async with httpx.AsyncClient(
            auth=auth,
            headers=headers,
            follow_redirects=True,
            timeout=10,
        ) as client:
            resp = await client.get(f"{cfg.confluence_server.rstrip('/')}/rest/api/space?limit=1")
            resp.raise_for_status()
        return {"name": "confluence_cli", "status": "ok", "message": cfg.confluence_server}
    except Exception as e:
        return {"name": "confluence_cli", "status": "error", "message": str(e)}


class ConfluenceCredentials:
    def __init__(self) -> None:
        cfg = ExtSettings()
        self.server = cfg.confluence_server
        self.token = cfg.confluence_token
        self.username = cfg.confluence_username
        self.password = cfg.confluence_password
        # Require either a PAT token OR username+password
        if not self.token and not self.username:
            raise KeyError("CONFLUENCE_TOKEN")
        if not self.token and not self.password:
            raise KeyError("CONFLUENCE_PASSWORD")

    def client(self) -> Confluence:
        if self.token:
            return Confluence(url=self.server, token=self.token)
        return Confluence(url=self.server, username=self.username, password=self.password)

    def http_auth(self) -> tuple[str, str]:
        # For direct HTTP calls (attachment downloads): use basic auth.
        # With PAT, Confluence accepts the token as the password with any username.
        if self.token:
            return (self.username or "token", self.token)
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


def _confluence_summary(tool_args: dict[str, Any]) -> str:
    cmd = tool_args.get("command", "")
    page_id = _summary_args(tool_args).get("page_id", "")
    return f"{cmd} {page_id}".strip() if page_id else cmd


def _parse_int(val: Any, default: int) -> int:
    """Parse val as int, falling back to default on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _str_id(val: Any, field: str) -> str:
    """Coerce an ID field to string (LLMs often pass integers for IDs)."""
    if val is None:
        raise KeyError(field)
    return str(val)


@tool(summary=_confluence_summary, health_check=health)
async def confluence_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute a Confluence operation.

    Auth is read from env vars: CONFLUENCE_SERVER, CONFLUENCE_TOKEN (preferred),
    or CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD.

    IMPORTANT — IDs: page_id and attachment_id must be numeric strings like "12345678".
    If you only have a page URL, extract the numeric ID from it (the number after /pages/).
    Do NOT pass URL fragments or titles where an ID is required.

    IMPORTANT — body format: whenever a "body" field is required for create_page or
    update_page, the content MUST be in Confluence Storage Format (a subset of XHTML).
    Examples:
      Plain paragraph : <p>Hello world</p>
      Heading         : <h2>Section</h2>
      Bullet list     : <ul><li>item</li></ul>
      Code block      : <ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body></ac:structured-macro>
    Do NOT pass plain text or Markdown as body — it will render incorrectly.

    Supported commands
    ──────────────────

    "search"
        CQL search returning matching pages/content.
        Required : cql (str) — CQL query, e.g. 'space = "TEAM" AND title ~ "meeting"'
        Optional : limit (int, default 10) — max results to return
        Returns  : {total, results: [{id, title, type, space, url, last_modified, excerpt}]}

    "get_page"
        Fetch full page content by numeric page ID.
        Required : page_id (str | int) — numeric page ID, e.g. "12345678"
        Returns  : {id, title, type, space, version, created_by, created, body (storage HTML), ancestors}

    "get_page_by_title"
        Fetch a page by space key + exact title.
        Required : space_key (str) — e.g. "TEAM"
                   title (str)     — exact page title
        Returns  : same shape as get_page, or null if not found

    "create_page"
        Create a new page in a space.
        Required : space_key (str) — target space key
                   title (str)     — page title (must be unique within the space)
                   body (str)      — page content in Confluence Storage Format (XHTML)
        Optional : parent_id (str | int) — numeric ID of the parent page
        Returns  : {created (id), title, url}

    "update_page"
        Update an existing page's title and/or body. Omit a field to keep it unchanged.
        Required : page_id (str | int) — numeric page ID
        Optional : title (str) — new title (kept unchanged if omitted)
                   body (str)  — new body in Confluence Storage Format (kept unchanged if omitted)
        Returns  : {updated (id), title, version, url}

    "get_spaces"
        List Confluence spaces accessible to the authenticated user.
        Optional : limit (int, default 25) — max spaces to return
        Returns  : [{key, name, type}]

    "get_page_children"
        List direct child pages of a page.
        Required : page_id (str | int)
        Optional : limit (int, default 20)
        Returns  : [{id, title, url}]

    "get_comments"
        Get all comments on a page.
        Required : page_id (str | int)
        Returns  : [{id, author, created, body (HTML)}]

    "add_comment"
        Add a plain-text comment to a page. The body is plain text (not storage format).
        Required : page_id (str | int)
                   body (str) — plain text comment content
        Returns  : {comment_id, created}

    "get_attachments"
        List all attachments on a page with metadata.
        Required : page_id (str | int)
        Returns  : [{id, title, filename, mime_type, size, created, author, download_url}]

    "download_attachment"
        Download an attachment file to disk. Use get_attachments first to find the attachment_id.
        Required : page_id (str | int)      — the page the attachment belongs to
                   attachment_id (str | int) — attachment ID from get_attachments (e.g. "att12345678")
        Optional : save_path (str) — absolute path to save the file; defaults to WORK_DIR/<filename>
        Returns  : {saved_to, size, filename}

    Args:
        command: The operation to perform (see list above).
        args: Parameters for the operation as a dict.
    """
    if args is None:
        args = {}

    try:
        creds = ConfluenceCredentials()
        confluence = creds.client()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Confluence credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  CONFLUENCE_SERVER=https://your-confluence.example.com\n"
            "  CONFLUENCE_TOKEN=your-personal-access-token\n"
            "  (or CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD for basic auth)\n"
        )

    try:
        if command == "search":
            cql = args.get("cql")
            if not cql:
                raise ToolError("missing required arg 'cql' for command 'search'.")
            limit = _parse_int(args.get("limit", 10), 10)
            results = confluence.cql(cql, limit=limit) or {}
            pages = results.get("results", [])
            simplified = [
                {
                    "id": p.get("content", {}).get("id"),
                    "title": p.get("content", {}).get("title"),
                    "type": p.get("content", {}).get("type"),
                    "space": p.get("resultGlobalContainer", {}).get("title"),
                    "url": p.get("url"),
                    "last_modified": p.get("lastModified"),
                    "excerpt": p.get("excerpt"),
                }
                for p in pages
            ]
            return _fmt({"total": len(simplified), "results": simplified})

        elif command == "get_page":
            page_id = _str_id(args.get("page_id"), "page_id")
            page = confluence.get_page_by_id(page_id, expand="body.storage,version,space,ancestors")
            if not isinstance(page, dict):
                raise ToolError(f"Page '{page_id}' not found.")
            return _fmt(_page_to_dict(page))

        elif command == "get_page_by_title":
            space_key = args.get("space_key")
            title = args.get("title")
            if not space_key:
                raise ToolError("missing required arg 'space_key' for command 'get_page_by_title'.")
            if not title:
                raise ToolError("missing required arg 'title' for command 'get_page_by_title'.")
            page = confluence.get_page_by_title(
                space_key, title, expand="body.storage,version,space"
            )
            if page is None:
                return _fmt(None)
            return _fmt(_page_to_dict(page))

        elif command == "create_page":
            space_key = args.get("space_key")
            title = args.get("title")
            if not space_key:
                raise ToolError("missing required arg 'space_key' for command 'create_page'.")
            if not title:
                raise ToolError("missing required arg 'title' for command 'create_page'.")
            body = args.get("body", "")
            if not isinstance(body, str):
                raise ToolError(
                    "'body' must be a string in Confluence Storage Format (XHTML), not "
                    f"{type(body).__name__}."
                )
            parent_id = args.get("parent_id")
            if parent_id is not None:
                parent_id = str(parent_id)
            page = confluence.create_page(
                space=space_key,
                title=title,
                body=body,
                parent_id=parent_id,
                representation="storage",
            )
            if not isinstance(page, dict):
                raise ToolError("Failed to create page.")
            return _fmt(
                {
                    "created": page.get("id"),
                    "title": page.get("title"),
                    "url": _page_url(creds.server, page),
                }
            )

        elif command == "update_page":
            page_id = _str_id(args.get("page_id"), "page_id")
            title = args.get("title")
            body = args.get("body")
            if body is not None and not isinstance(body, str):
                raise ToolError(
                    "'body' must be a string in Confluence Storage Format (XHTML), not "
                    f"{type(body).__name__}."
                )
            # Fetch current page to get title/version if not provided
            current = confluence.get_page_by_id(page_id, expand="body.storage,version") or {}
            if title is None:
                title = current.get("title", "")
            if body is None:
                body = current.get("body", {}).get("storage", {}).get("value", "")
            page = confluence.update_page(
                page_id=page_id,
                title=title,
                body=body,
                representation="storage",
            )
            page = page or {}
            return _fmt(
                {
                    "updated": page.get("id"),
                    "title": page.get("title"),
                    "version": page.get("version", {}).get("number"),
                    "url": _page_url(creds.server, page),
                }
            )

        elif command == "get_spaces":
            limit = _parse_int(args.get("limit", 25), 25)
            result = confluence.get_all_spaces(limit=limit) or {}
            spaces = result.get("results", []) if isinstance(result, dict) else []
            return _fmt(
                [
                    {
                        "key": s.get("key"),
                        "name": s.get("name"),
                        "type": s.get("type"),
                    }
                    for s in spaces
                ]
            )

        elif command == "get_page_children":
            page_id = _str_id(args.get("page_id"), "page_id")
            limit = _parse_int(args.get("limit", 20), 20)
            children = confluence.get_page_child_by_type(page_id, type="page", limit=limit) or []
            return _fmt(
                [
                    {
                        "id": c.get("id"),
                        "title": c.get("title"),
                        "url": _page_url(creds.server, c),
                    }
                    for c in children
                ]
            )

        elif command == "get_comments":
            page_id = _str_id(args.get("page_id"), "page_id")
            comments = confluence.get_page_comments(page_id, expand="body.view", depth="all") or {}
            results = comments.get("results", [])
            return _fmt(
                [
                    {
                        "id": c.get("id"),
                        "author": c.get("version", {}).get("by", {}).get("displayName"),
                        "created": c.get("version", {}).get("when"),
                        "body": c.get("body", {}).get("view", {}).get("value"),
                    }
                    for c in results
                ]
            )

        elif command == "add_comment":
            page_id = _str_id(args.get("page_id"), "page_id")
            body = args.get("body")
            if body is None:
                raise ToolError("missing required arg 'body' for command 'add_comment'.")
            comment = confluence.add_comment(page_id, str(body)) or {}
            return _fmt(
                {
                    "comment_id": comment.get("id"),
                    "created": comment.get("version", {}).get("when"),
                }
            )

        elif command == "get_attachments":
            page_id = _str_id(args.get("page_id"), "page_id")
            attachments = confluence.get_attachments_from_content(page_id) or {}
            results = attachments.get("results", [])
            return _fmt(
                [
                    {
                        "id": a.get("id"),
                        "title": a.get("title"),
                        "filename": a.get("title"),
                        "mime_type": a.get("metadata", {}).get("mediaType"),
                        "size": a.get("extensions", {}).get("fileSize"),
                        "created": a.get("version", {}).get("when"),
                        "author": a.get("version", {}).get("by", {}).get("displayName"),
                        "download_url": a.get("_links", {}).get("download"),
                    }
                    for a in results
                ]
            )

        elif command == "download_attachment":
            page_id = _str_id(args.get("page_id"), "page_id")
            attachment_id = _str_id(args.get("attachment_id"), "attachment_id")
            # Get attachment metadata to find filename and download URL
            attachments = confluence.get_attachments_from_content(page_id) or {}
            attachment = next(
                (
                    a
                    for a in attachments.get("results", [])
                    # match by id with or without "att" prefix
                    if a.get("id") == attachment_id
                    or a.get("id") == f"att{attachment_id}"
                    or str(a.get("id", "")).lstrip("att") == attachment_id.lstrip("att")
                ),
                None,
            )
            if attachment is None:
                raise ToolError(
                    f"Attachment '{attachment_id}' not found on page '{page_id}'. "
                    "Use get_attachments to list available attachments and their IDs."
                )
            filename = attachment.get("title", attachment_id)
            download_path = attachment.get("_links", {}).get("download", "")
            url = creds.server.rstrip("/") + download_path

            save_path = args.get("save_path")
            if save_path:
                dest = Path(save_path)
            else:
                from aiyo.config import settings

                dest = Path(settings.work_dir) / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            with httpx.Client(auth=creds.http_auth(), follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return _fmt({"saved_to": str(dest), "size": len(resp.content), "filename": filename})

        else:
            raise ToolError(
                f"Unknown command '{command}'. "
                "Valid commands: search, get_page, get_page_by_title, create_page, update_page, "
                "get_spaces, get_page_children, get_comments, add_comment, "
                "get_attachments, download_attachment."
            )

    except KeyError as e:
        raise ToolError(f"Missing required arg {e} for command '{command}'.") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e)) from e


def _page_to_dict(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "title": page.get("title"),
        "type": page.get("type"),
        "space": page.get("space", {}).get("key"),
        "version": page.get("version", {}).get("number"),
        "created_by": page.get("version", {}).get("by", {}).get("displayName"),
        "created": page.get("version", {}).get("when"),
        "body": page.get("body", {}).get("storage", {}).get("value"),
        "ancestors": [
            {"id": a.get("id"), "title": a.get("title")} for a in page.get("ancestors", [])
        ],
    }


def _page_url(server: str, page: dict[str, Any]) -> str:
    webui = page.get("_links", {}).get("webui", "")
    return server.rstrip("/") + webui
