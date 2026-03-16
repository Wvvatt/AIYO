"""Confluence tool: a single CLI-style interface for all Confluence operations.

Auth is read from environment variables (or .env file):
  CONFLUENCE_SERVER   — Confluence instance URL (default: https://confluence.amlogic.com/)
  CONFLUENCE_USERNAME — username or email
  CONFLUENCE_PASSWORD — password or API token
"""

import json
from pathlib import Path
from typing import Any

import httpx
from atlassian import Confluence

from aml.config import AmlSettings


class ConfluenceCredentials:
    def __init__(self) -> None:
        cfg = AmlSettings()
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


async def confluence_cli(command: str, args: dict[str, Any] | None = None) -> str:
    """Execute a Confluence operation. Auth is configured via CONFLUENCE_SERVER / CONFLUENCE_USERNAME / CONFLUENCE_PASSWORD env vars.

    Supported commands and their args:

    - "search"           — CQL search for pages.
        args: {"cql": "title ~ \"meeting\"", "limit": 10}
    - "get_page"         — Fetch a single page by ID.
        args: {"page_id": "12345678"}
    - "get_page_by_title" — Fetch a page by space key and title.
        args: {"space_key": "TEAM", "title": "My Page"}
    - "create_page"      — Create a new page.
        args: {"space_key": "TEAM", "title": "New Page", "body": "<p>content</p>",
                "parent_id": "12345678"}  # parent_id optional
    - "update_page"      — Update an existing page's title and/or body.
        args: {"page_id": "12345678", "title": "New Title", "body": "<p>new content</p>"}
    - "get_spaces"       — List accessible Confluence spaces.
        args: {"limit": 25}
    - "get_page_children" — List child pages of a page.
        args: {"page_id": "12345678", "limit": 20}
    - "get_comments"     — Get comments on a page.
        args: {"page_id": "12345678"}
    - "add_comment"      — Add a comment to a page.
        args: {"page_id": "12345678", "body": "comment text"}
    - "get_attachments"  — List all attachments on a page.
        args: {"page_id": "12345678"}
    - "download_attachment" — Download an attachment to a local path.
        args: {"attachment_id": "att12345678", "page_id": "12345678", "save_path": "/tmp/file.txt"}
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
        creds = ConfluenceCredentials()
        confluence = creds.client()
    except KeyError as e:
        return f"Error: missing environment variable {e}. Set CONFLUENCE_USERNAME and CONFLUENCE_PASSWORD."

    try:
        if command == "search":
            cql = args.get("cql", "")
            limit = int(args.get("limit", 10))
            results = confluence.cql(cql, limit=limit)
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
            page_id = args["page_id"]
            page = confluence.get_page_by_id(page_id, expand="body.storage,version,space,ancestors")
            return _fmt(_page_to_dict(page))

        elif command == "get_page_by_title":
            space_key = args["space_key"]
            title = args["title"]
            page = confluence.get_page_by_title(
                space_key, title, expand="body.storage,version,space"
            )
            if page is None:
                return _fmt(None)
            return _fmt(_page_to_dict(page))

        elif command == "create_page":
            space_key = args["space_key"]
            title = args["title"]
            body = args.get("body", "")
            parent_id = args.get("parent_id")
            page = confluence.create_page(
                space=space_key,
                title=title,
                body=body,
                parent_id=parent_id,
                representation="storage",
            )
            return _fmt(
                {
                    "created": page.get("id"),
                    "title": page.get("title"),
                    "url": _page_url(creds.server, page),
                }
            )

        elif command == "update_page":
            page_id = args["page_id"]
            title = args.get("title")
            body = args.get("body")
            # Fetch current page to get title/version if not provided
            current = confluence.get_page_by_id(page_id, expand="body.storage,version")
            if title is None:
                title = current.get("title", "")
            if body is None:
                body = current.get("body", {}).get("storage", {}).get("value", "")
            version = current.get("version", {}).get("number", 1)
            page = confluence.update_page(
                page_id=page_id,
                title=title,
                body=body,
                version_increment=1,
                representation="storage",
            )
            return _fmt(
                {
                    "updated": page.get("id"),
                    "title": page.get("title"),
                    "version": page.get("version", {}).get("number"),
                    "url": _page_url(creds.server, page),
                }
            )

        elif command == "get_spaces":
            limit = int(args.get("limit", 25))
            result = confluence.get_all_spaces(limit=limit)
            spaces = result.get("results", []) if isinstance(result, dict) else result
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
            page_id = args["page_id"]
            limit = int(args.get("limit", 20))
            children = confluence.get_page_child_by_type(page_id, type="page", limit=limit)
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
            page_id = args["page_id"]
            comments = confluence.get_page_comments(page_id, expand="body.view", depth="all")
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
            page_id = args["page_id"]
            body = args["body"]
            comment = confluence.add_comment(page_id, body)
            return _fmt(
                {
                    "comment_id": comment.get("id"),
                    "created": comment.get("version", {}).get("when"),
                }
            )

        elif command == "get_attachments":
            page_id = args["page_id"]
            attachments = confluence.get_attachments_from_content(page_id)
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
            page_id = args["page_id"]
            attachment_id = args["attachment_id"]
            # Get attachment metadata to find filename and download URL
            attachments = confluence.get_attachments_from_content(page_id)
            attachment = next(
                (a for a in attachments.get("results", []) if a.get("id") == attachment_id),
                None,
            )
            if attachment is None:
                return f"Error: attachment '{attachment_id}' not found on page '{page_id}'."
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
            return (
                f"Unknown command '{command}'. "
                "Valid commands: search, get_page, get_page_by_title, create_page, update_page, "
                "get_spaces, get_page_children, get_comments, add_comment, "
                "get_attachments, download_attachment."
            )

    except KeyError as e:
        return f"Error: missing required arg {e} for command '{command}'."
    except Exception as e:
        return f"Error: {e}"


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
