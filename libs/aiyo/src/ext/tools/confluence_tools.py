"""Confluence tools.

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
from ext.infra.credentials import ConfluenceCredentials
from ext.tools._health_cache import cached_health


async def health() -> dict[str, Any]:
    """Check Confluence connection health.

    Returns:
        Dict with keys: name, status, message
        status: "ok" | "error" | "not_configured"
    """
    async def _probe() -> dict[str, Any]:
        cfg = ExtSettings()
        if not cfg.confluence_server:
            return {
                "name": "confluence",
                "status": "not_configured",
                "message": "CONFLUENCE_SERVER missing",
            }

        has_token = bool(cfg.confluence_token)
        has_basic = bool(cfg.confluence_username and cfg.confluence_password)

        if not has_token and not has_basic:
            return {
                "name": "confluence",
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
                resp = await client.get(
                    f"{cfg.confluence_server.rstrip('/')}/rest/api/space?limit=1"
                )
                resp.raise_for_status()
            return {"name": "confluence", "status": "ok", "message": cfg.confluence_server}
        except Exception as e:
            return {"name": "confluence", "status": "error", "message": str(e)}

    return await cached_health("confluence", _probe)


def _fmt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _credentials_and_client() -> tuple[ConfluenceCredentials, Confluence]:
    try:
        creds = ConfluenceCredentials()
        return creds, creds.client()
    except KeyError as e:
        raise ToolError(
            f"CREDENTIALS_REQUIRED: Confluence credentials are not configured ({e} is missing).\n\n"
            "Stop here. Do not search for alternatives or retry.\n"
            "Tell the user to add the following to ~/.aiyo/.env and restart:\n\n"
            "  CONFLUENCE_SERVER=https://your-confluence.example.com\n"
            "  CONFLUENCE_TOKEN=your-personal-access-token\n"
            "  (or CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD for basic auth)\n"
        ) from e
    except Exception as exc:
        raise ToolError(f"Failed to initialize Confluence client: {exc}") from exc


def _confluence_error(exc: Exception) -> ToolError:
    if isinstance(exc, KeyError):
        return ToolError(f"missing required arg '{str(exc).strip(chr(39) + chr(34))}'.")
    if isinstance(exc, ToolError):
        return exc
    return ToolError(str(exc))


def _field_summary(*names: str):
    def summary(tool_args: dict[str, Any]) -> str:
        return " ".join(str(tool_args.get(name)) for name in names if tool_args.get(name))

    return summary


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


@tool(gatherable=True, summary=_field_summary("cql"), health_check=health)
async def confluence_search(cql: str, limit: int = 10) -> str:
    """Search Confluence content with CQL."""
    _, confluence = _credentials_and_client()
    try:
        if not cql:
            raise ToolError("missing required arg 'cql'.")
        results = confluence.cql(cql, limit=_parse_int(limit, 10)) or {}
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
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("page_id"), health_check=health)
async def confluence_get_page(page_id: str | int) -> str:
    """Fetch full Confluence page content by page id."""
    _, confluence = _credentials_and_client()
    try:
        page_id = _str_id(page_id, "page_id")
        page = confluence.get_page_by_id(page_id, expand="body.storage,version,space,ancestors")
        if not isinstance(page, dict):
            raise ToolError(f"Page '{page_id}' not found.")
        return _fmt(_page_to_dict(page))
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("space_key", "title"), health_check=health)
async def confluence_get_page_by_title(space_key: str, title: str) -> str:
    """Fetch a Confluence page by space key and exact title."""
    _, confluence = _credentials_and_client()
    try:
        if not space_key:
            raise ToolError("missing required arg 'space_key'.")
        if not title:
            raise ToolError("missing required arg 'title'.")
        page = confluence.get_page_by_title(
            space_key, title, expand="body.storage,version,space"
        )
        if page is None:
            return _fmt(None)
        return _fmt(_page_to_dict(page))
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(gatherable=True, health_check=health)
async def confluence_get_spaces(limit: int = 25) -> str:
    """List Confluence spaces."""
    _, confluence = _credentials_and_client()
    try:
        result = confluence.get_all_spaces(limit=_parse_int(limit, 25)) or {}
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
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("page_id"), health_check=health)
async def confluence_get_page_children(page_id: str | int, limit: int = 20) -> str:
    """List direct child pages of a Confluence page."""
    creds, confluence = _credentials_and_client()
    try:
        page_id = _str_id(page_id, "page_id")
        children = confluence.get_page_child_by_type(
            page_id, type="page", limit=_parse_int(limit, 20)
        ) or []
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
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(gatherable=True, summary=_field_summary("page_id"), health_check=health)
async def confluence_get_attachments(page_id: str | int) -> str:
    """List attachments on a Confluence page."""
    _, confluence = _credentials_and_client()
    try:
        page_id = _str_id(page_id, "page_id")
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
    except Exception as exc:
        raise _confluence_error(exc) from exc


@tool(summary=_field_summary("page_id", "attachment_id"), health_check=health)
async def confluence_download_attachment(
    page_id: str | int,
    attachment_id: str | int,
    save_path: str | None = None,
) -> str:
    """Download a Confluence attachment."""
    creds, confluence = _credentials_and_client()
    try:
        page_id = _str_id(page_id, "page_id")
        attachment_id = _str_id(attachment_id, "attachment_id")
        attachments = confluence.get_attachments_from_content(page_id) or {}
        attachment = next(
            (
                a
                for a in attachments.get("results", [])
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
        url = creds.server.rstrip("/") + attachment.get("_links", {}).get("download", "")
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
    except Exception as exc:
        raise _confluence_error(exc) from exc


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
