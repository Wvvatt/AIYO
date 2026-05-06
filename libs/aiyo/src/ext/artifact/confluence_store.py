"""Confluence-backed artifact store for analyze mode."""

from __future__ import annotations

from typing import Any

from aiyo.tools.exceptions import ToolError
from atlassian import Confluence
from bs4 import BeautifulSoup

from .storage_xml import (
    EMPTY_SECTION_BODY,
    artifact_section_index,
    build_artifact_section,
    find_artifact_section,
    list_artifact_sections,
    parse_storage,
    serialize_storage,
    upsert_section,
)


class ConfluenceArtifactStore:
    """Async artifact store backed by Confluence child pages."""

    def __init__(self, client: Confluence, artifact_root_page_id: str) -> None:
        self.client = client
        self.artifact_root_page_id = str(artifact_root_page_id)

        artifact_root = self.client.get_page_by_id(self.artifact_root_page_id, expand="space")
        if not isinstance(artifact_root, dict):
            raise ToolError(f"Artifact root page '{self.artifact_root_page_id}' was not found.")

        self._space_key = str(artifact_root.get("space", {}).get("key") or "").strip()
        self._artifact_root_title = str(artifact_root.get("title") or "").strip()
        if not self._space_key or not self._artifact_root_title:
            raise ToolError(
                f"Artifact root page '{self.artifact_root_page_id}' is missing required metadata."
            )

    async def list_artifacts(self, title: str = "") -> list[str]:
        """Return child-page titles, or section titles under one artifact page."""
        title = str(title or "").strip()
        if title:
            page = self._find_artifact_page(title)
            if page is None:
                return []

            body = str(page.get("body", {}).get("storage", {}).get("value") or "")
            return list(list_artifact_sections(body).keys())

        children = self.client.get_page_child_by_type(
            self.artifact_root_page_id, type="page", limit=500
        )
        return [str(child.get("title") or "") for child in children or [] if child.get("title")]

    async def get_artifact(self, title: str, section: str = "") -> dict[str, str] | str | None:
        """Return all sections for a page or one section when requested."""
        page = self._find_artifact_page(title)
        if page is None:
            return None

        body = str(page.get("body", {}).get("storage", {}).get("value") or "")
        sections = list_artifact_sections(body)
        if section:
            return sections.get(section)
        return sections

    async def upsert_artifact_section(
        self,
        title: str,
        section: str,
        content: str,
    ) -> dict[str, Any]:
        """Create/update one artifact section on a child page."""
        page, created_page = self._get_or_create_artifact_page(title)
        current_page, soup = self._load_page(str(page["id"]))
        current_section = find_artifact_section(soup, section)
        new_section = build_artifact_section(soup, section, content)
        replaced = upsert_section(soup, current_section, new_section)

        self._write_back(current_page, soup, f"Upsert artifact {title}/{section}")
        return {
            "page_id": str(current_page["id"]),
            "page_url": self._page_url(current_page),
            "row_index": artifact_section_index(soup, section),
            "updated": replaced,
            "created_page": created_page,
            "size": len(content),
        }

    async def delete_artifact(self, title: str, section: str = "") -> bool:
        """Delete a page under the artifact root, or one section when requested."""
        page = self._find_artifact_page(title)
        if page is None:
            return False

        section = str(section or "").strip()
        if section:
            current_page, soup = self._load_page(str(page["id"]))
            current_section = find_artifact_section(soup, section)
            if current_section is None:
                return False

            current_section.decompose()
            self._write_back(current_page, soup, f"Delete artifact section {title}/{section}")
            return True

        self._delete_page(str(page["id"]))
        return True

    def _load_page(self, page_id: str) -> tuple[dict[str, Any], BeautifulSoup]:
        page = self.client.get_page_by_id(page_id, expand="body.storage,version,space,ancestors")
        if not isinstance(page, dict):
            raise ToolError(f"Confluence page '{page_id}' was not found.")

        body = page.get("body", {}).get("storage", {}).get("value") or ""
        return page, parse_storage(str(body))

    def _write_back(self, page: dict[str, Any], soup: BeautifulSoup, version_comment: str) -> None:
        page_id = str(page.get("id") or "")
        title = str(page.get("title") or "")
        if not page_id or not title:
            raise ToolError("Confluence artifact update failed: page id/title missing.")

        self.client.update_page(
            page_id=page_id,
            title=title,
            body=serialize_storage(soup),
            representation="storage",
            version_comment=version_comment,
            always_update=True,
        )

    def _find_artifact_page(self, title: str) -> dict[str, Any] | None:
        page = self.client.get_page_by_title(
            space=self._space_key,
            title=title,
            expand="body.storage,version,space,ancestors",
        )
        if isinstance(page, dict) and self._page_is_under_root(page):
            return page

        children = self.client.get_page_child_by_type(
            self.artifact_root_page_id, type="page", limit=500
        )
        for child in children or []:
            if str(child.get("title") or "") == title:
                return self.client.get_page_by_id(
                    str(child["id"]), expand="body.storage,version,space,ancestors"
                )
        return None

    def _get_or_create_artifact_page(self, title: str) -> tuple[dict[str, Any], bool]:
        page = self._find_artifact_page(title)
        if page is not None:
            return page, False

        created = self.client.create_page(
            space=self._space_key,
            title=title,
            body=EMPTY_SECTION_BODY,
            parent_id=self.artifact_root_page_id,
            representation="storage",
        )
        if not isinstance(created, dict) or "id" not in created:
            raise ToolError(f"Failed to create artifact page '{title}'.")
        return (
            self.client.get_page_by_id(
                str(created["id"]), expand="body.storage,version,space,ancestors"
            ),
            True,
        )

    def _page_is_under_root(self, page: dict[str, Any]) -> bool:
        ancestors = page.get("ancestors") or []
        return any(
            str(ancestor.get("id") or "") == self.artifact_root_page_id for ancestor in ancestors
        )

    def _page_url(self, page: dict[str, Any]) -> str:
        links = page.get("_links") or {}
        webui = str(links.get("webui") or "")
        if webui.startswith("http://") or webui.startswith("https://"):
            return webui
        base = str(links.get("base") or getattr(self.client, "url", "")).rstrip("/")
        if webui:
            return f"{base}{webui}" if base else webui
        page_id = str(page.get("id") or "")
        if base and page_id:
            return f"{base}/pages/viewpage.action?pageId={page_id}"
        return page_id

    def _delete_page(self, page_id: str) -> None:
        if hasattr(self.client, "remove_page"):
            self.client.remove_page(page_id)
            return
        if hasattr(self.client, "delete_page"):
            self.client.delete_page(page_id)
            return
        raise ToolError("Confluence client does not support page deletion.")
