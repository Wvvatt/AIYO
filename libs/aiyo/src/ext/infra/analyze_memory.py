"""Confluence-backed storage for analyze-mode artifacts and history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiyo.tools.exceptions import ToolError
from atlassian import Confluence
from bs4 import BeautifulSoup, Tag

from .analyze_models import HistoryEntry

XML_ROOT = (
    '<root xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier">'
)
ARTIFACT_PAGE_TITLE_PREFIX = "MMAD - Memory - Artifact - "
EMPTY_SECTION_BODY = "<p></p>"
MACRO_NAME = "panel"
SECTION_ARTIFACT = "artifact"
SECTION_HISTORY = "history"


def build_artifact_row(title: str, content: str) -> dict[str, str]:
    """Build a single artifact entry."""
    return {
        "Timestamp": datetime.now().isoformat(),
        "Title": title,
        "Content": content,
    }


def build_history_row(issue_key: str, summary: str, tags: list[str]) -> dict[str, str]:
    """Build a single history entry."""
    return {
        "Issue": issue_key,
        "Summary": summary,
        "Tags": ", ".join(tags),
        "Timestamp": datetime.now().isoformat(),
    }


def _parse_storage(body: str) -> BeautifulSoup:
    return BeautifulSoup(f"{XML_ROOT}{body}</root>", features="xml")


def _serialize_storage(soup: BeautifulSoup) -> str:
    root = soup.find("root")
    if root is None:
        raise ToolError("Confluence storage parsing failed: missing synthetic root.")
    return "".join(str(child) for child in root.contents)


def _artifact_heading(title: str, timestamp: str) -> str:
    return f"{title}-{timestamp}"


def _history_heading(issue_key: str, timestamp: str) -> str:
    return f"{issue_key}-{timestamp}"


class ConfluenceMemory:
    """CRUD facade for analyze-mode memory stored in Confluence macros."""

    def __init__(
        self,
        client: Confluence,
        artifact_root_page_id: str,
        history_page_id: str,
    ) -> None:
        self.client = client
        self.artifact_root_page_id = str(artifact_root_page_id)
        self.history_page_id = str(history_page_id)

        artifact_root = self.client.get_page_by_id(self.artifact_root_page_id, expand="space")
        if not isinstance(artifact_root, dict):
            raise ToolError(f"Artifact root page '{self.artifact_root_page_id}' was not found.")

        self._space_key = str(artifact_root.get("space", {}).get("key") or "").strip()
        self._artifact_root_title = str(artifact_root.get("title") or "").strip()
        if not self._space_key or not self._artifact_root_title:
            raise ToolError(
                f"Artifact root page '{self.artifact_root_page_id}' is missing required metadata."
            )

    def upsert_artifact(self, issue_key: str, title: str, content: str) -> dict[str, Any]:
        """Insert or replace one artifact section by title on the issue child page."""
        child_page = self._get_or_create_artifact_page(issue_key)
        page, soup = self._load_page(str(child_page["id"]))
        entry = build_artifact_row(title, content)
        new_section = self._build_artifact_section(soup, entry)
        current_section = self._find_macro_by_title(soup, SECTION_ARTIFACT, title)
        replaced = self._upsert_section(soup, current_section, new_section)

        self._write_back(page, soup, f"Upsert artifact {issue_key}/{title}")
        child_page_url = self._page_url(child_page)
        return {
            "child_page_id": str(child_page["id"]),
            "child_page_url": child_page_url,
            "row_index": self._macro_index_by_title(soup, SECTION_ARTIFACT, title),
            "updated": replaced,
        }

    def list_artifacts(self, issue_key: str) -> list[dict[str, str]]:
        """List all artifact entries for an issue."""
        child_page = self._find_artifact_page(issue_key)
        if child_page is None:
            return []

        _, soup = self._load_page(str(child_page["id"]))
        return self._list_artifact_entries_from_soup(soup)

    def get_artifact(self, issue_key: str, title: str) -> dict[str, str] | None:
        """Return the newest artifact row with a matching title."""
        matches = [row for row in self.list_artifacts(issue_key) if row.get("Title") == title]
        return matches[-1] if matches else None

    def get_artifact_page_storage(self, issue_key: str) -> dict[str, str] | None:
        """Return raw storage content for the issue artifact page."""
        page = self._find_artifact_page(issue_key)
        if page is None:
            return None

        body = page.get("body", {}).get("storage", {}).get("value") or ""
        return {
            "page_id": str(page.get("id") or ""),
            "page_url": self._page_url(page),
            "content": str(body),
        }

    def parse_artifact_storage(self, body: str) -> list[dict[str, str]]:
        """Parse raw artifact page storage into structured entries."""
        return self._list_artifact_entries_from_soup(_parse_storage(body))

    def upsert_history(
        self,
        issue_key: str,
        summary: str,
        tags: list[str],
    ) -> dict[str, Any]:
        """Insert or replace a history entry keyed by Jira issue."""
        page, soup = self._load_page(self.history_page_id)
        entry = build_history_row(issue_key, summary, tags)
        new_section = self._build_history_section(soup, entry)
        current_section = self._find_macro_by_issue(soup, SECTION_HISTORY, issue_key)
        replaced = self._upsert_section(soup, current_section, new_section)

        self._write_back(page, soup, f"Upsert history {issue_key}")
        return {"issue_key": issue_key, "updated": replaced}

    def list_history(self) -> list[HistoryEntry]:
        """List all history entries from the history page."""
        _, soup = self._load_page(self.history_page_id)
        entries: list[HistoryEntry] = []
        for row in self._list_history_entries_from_soup(soup):
            tags = [part.strip() for part in row.get("Tags", "").split(",") if part.strip()]
            entries.append(
                HistoryEntry(
                    issue=row.get("Issue", ""),
                    summary=row.get("Summary", ""),
                    tags=tags,
                    ts=row.get("Timestamp", datetime.now().isoformat()),
                )
            )
        return entries

    def _load_page(self, page_id: str) -> tuple[dict[str, Any], BeautifulSoup]:
        page = self.client.get_page_by_id(page_id, expand="body.storage,version,space,ancestors")
        if not isinstance(page, dict):
            raise ToolError(f"Confluence page '{page_id}' was not found.")

        body = page.get("body", {}).get("storage", {}).get("value") or ""
        return page, _parse_storage(body)

    def _write_back(self, page: dict[str, Any], soup: BeautifulSoup, version_comment: str) -> None:
        page_id = str(page.get("id") or "")
        title = str(page.get("title") or "")
        if not page_id or not title:
            raise ToolError("Confluence memory update failed: page id/title missing.")

        self.client.update_page(
            page_id=page_id,
            title=title,
            body=_serialize_storage(soup),
            representation="storage",
            version_comment=version_comment,
            always_update=True,
        )

    def _find_artifact_page(self, issue_key: str) -> dict[str, Any] | None:
        title = f"{ARTIFACT_PAGE_TITLE_PREFIX}{issue_key}"
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

    def _get_or_create_artifact_page(self, issue_key: str) -> dict[str, Any]:
        page = self._find_artifact_page(issue_key)
        if page is not None:
            return page

        title = f"{ARTIFACT_PAGE_TITLE_PREFIX}{issue_key}"
        created = self.client.create_page(
            space=self._space_key,
            title=title,
            body=EMPTY_SECTION_BODY,
            parent_id=self.artifact_root_page_id,
            representation="storage",
        )
        if not isinstance(created, dict) or "id" not in created:
            raise ToolError(f"Failed to create artifact page '{title}'.")
        return self.client.get_page_by_id(
            str(created["id"]), expand="body.storage,version,space,ancestors"
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

    def _root_tag(self, soup: BeautifulSoup) -> Tag:
        root = soup.find("root")
        if root is None:
            raise ToolError("Confluence storage parsing failed: missing synthetic root.")
        return root

    def _macro_sections(self, soup: BeautifulSoup, kind: str) -> list[Tag]:
        root = self._root_tag(soup)
        sections: list[Tag] = []
        for child in root.find_all(recursive=False):
            if child.name not in {"structured-macro", "ac:structured-macro"}:
                continue
            if self._macro_name(child) != MACRO_NAME:
                continue
            if self._macro_param(child, "aiyo-kind") != kind:
                continue
            sections.append(child)
        return sections

    def _find_macro_by_issue(self, soup: BeautifulSoup, kind: str, issue_key: str) -> Tag | None:
        return self._find_macro_by_param(soup, kind, "aiyo-issue", issue_key)

    def _find_macro_by_title(self, soup: BeautifulSoup, kind: str, title: str) -> Tag | None:
        return self._find_macro_by_param(soup, kind, "aiyo-title", title)

    def _find_macro_by_param(
        self,
        soup: BeautifulSoup,
        kind: str,
        param_name: str,
        param_value: str,
    ) -> Tag | None:
        for section in self._macro_sections(soup, kind):
            if self._macro_param(section, param_name) == param_value:
                return section
        return None

    def _macro_index_by_title(self, soup: BeautifulSoup, kind: str, title: str) -> int:
        for index, section in enumerate(self._macro_sections(soup, kind), start=1):
            if self._macro_param(section, "aiyo-title") == title:
                return index
        raise ToolError(f"Confluence memory is missing expected '{kind}' section '{title}'.")

    def _macro_name(self, macro: Tag) -> str:
        return str(macro.get("ac:name") or macro.get("name") or "")

    def _macro_param(self, macro: Tag, name: str) -> str:
        for param in macro.find_all(["parameter", "ac:parameter"], recursive=False):
            if str(param.get("ac:name") or param.get("name") or "") == name:
                return param.get_text()
        return ""

    def _macro_body(self, macro: Tag) -> Tag | None:
        return macro.find(["rich-text-body", "ac:rich-text-body"], recursive=False)

    def _new_section_macro(
        self,
        soup: BeautifulSoup,
        kind: str,
        title: str,
        metadata: dict[str, str],
    ) -> tuple[Tag, Tag]:
        macro = soup.new_tag("ac:structured-macro", attrs={"ac:name": MACRO_NAME})

        title_param = soup.new_tag("ac:parameter", attrs={"ac:name": "title"})
        title_param.string = title
        macro.append(title_param)

        kind_param = soup.new_tag("ac:parameter", attrs={"ac:name": "aiyo-kind"})
        kind_param.string = kind
        macro.append(kind_param)

        for key, value in metadata.items():
            param = soup.new_tag("ac:parameter", attrs={"ac:name": key})
            param.string = value
            macro.append(param)

        body = soup.new_tag("ac:rich-text-body")
        macro.append(body)
        return macro, body

    def _build_artifact_section(self, soup: BeautifulSoup, entry: dict[str, str]) -> Tag:
        section, body = self._new_section_macro(
            soup,
            SECTION_ARTIFACT,
            _artifact_heading(entry["Title"], entry["Timestamp"]),
            {
                "aiyo-title": entry["Title"],
                "aiyo-ts": entry["Timestamp"],
            },
        )
        block = soup.new_tag("pre")
        block.string = entry["Content"]
        body.append(block)
        return section

    def _build_history_section(self, soup: BeautifulSoup, entry: dict[str, str]) -> Tag:
        section, body = self._new_section_macro(
            soup,
            SECTION_HISTORY,
            _history_heading(entry["Issue"], entry["Timestamp"]),
            {
                "aiyo-issue": entry["Issue"],
                "aiyo-ts": entry["Timestamp"],
                "aiyo-tags": entry["Tags"],
            },
        )

        summary_line = soup.new_tag("p")
        summary_label = soup.new_tag("strong")
        summary_label.string = "Summary:"
        summary_line.append(summary_label)
        summary_line.append(f" {entry['Summary']}")

        tags_line = soup.new_tag("p")
        tags_label = soup.new_tag("strong")
        tags_label.string = "Tags:"
        tags_line.append(tags_label)
        tags_line.append(f" {entry['Tags']}")

        body.append(summary_line)
        body.append(tags_line)
        return section

    def _upsert_section(
        self,
        soup: BeautifulSoup,
        current_section: Tag | None,
        new_section: Tag,
    ) -> bool:
        if current_section is not None:
            current_section.replace_with(new_section)
            return True

        self._root_tag(soup).append(new_section)
        return False

    def _history_entry_from_section(self, section: Tag) -> dict[str, str]:
        summary = ""
        body = self._macro_body(section)
        if body is not None:
            summary_line = body.find("p", recursive=False)
            if summary_line is not None:
                full_text = summary_line.get_text(" ", strip=True)
                prefix = "Summary:"
                summary = full_text[len(prefix) :].strip() if full_text.startswith(prefix) else ""

        return {
            "Issue": self._macro_param(section, "aiyo-issue"),
            "Summary": summary,
            "Tags": self._macro_param(section, "aiyo-tags"),
            "Timestamp": self._macro_param(section, "aiyo-ts"),
        }

    def _list_artifact_entries_from_soup(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for section in self._macro_sections(soup, SECTION_ARTIFACT):
            body = self._macro_body(section)
            block = body.find("pre") if body is not None else None
            entries.append(
                {
                    "Timestamp": self._macro_param(section, "aiyo-ts"),
                    "Title": self._macro_param(section, "aiyo-title"),
                    "Content": block.get_text() if block is not None else "",
                }
            )
        return entries

    def _list_history_entries_from_soup(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        return [
            self._history_entry_from_section(section)
            for section in self._macro_sections(soup, SECTION_HISTORY)
        ]


__all__ = ["ConfluenceMemory", "build_artifact_row", "build_history_row"]
