"""Tests for the Confluence-backed artifact store."""

from __future__ import annotations

from copy import deepcopy

import pytest
from ext.artifact import ConfluenceArtifactStore


def _page(
    page_id: str,
    title: str,
    body: str,
    *,
    space: str = "TEAM",
    parent_id: str | None = None,
    ancestors: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "id": page_id,
        "title": title,
        "type": "page",
        "space": {"key": space},
        "parent_id": parent_id,
        "ancestors": ancestors or [],
        "body": {"storage": {"value": body}},
        "_links": {
            "base": "https://confluence.example.com",
            "webui": f"/pages/viewpage.action?pageId={page_id}",
        },
    }


class FakeConfluence:
    def __init__(self, pages: list[dict]):
        self.url = "https://confluence.example.com"
        self.pages = {str(page["id"]): deepcopy(page) for page in pages}
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.remove_calls: list[str] = []
        self._next_id = max(int(page_id) for page_id in self.pages) + 1

    def get_page_by_id(self, page_id, expand=None, status=None, version=None):
        page = self.pages.get(str(page_id))
        return deepcopy(page) if page else None

    def get_page_by_title(self, space, title, start=0, limit=1, expand=None, type="page"):
        for page in self.pages.values():
            if page["space"]["key"] == space and page["title"] == title:
                return deepcopy(page)
        return None

    def get_page_child_by_type(self, parent_id, type="page", limit=500):
        children = [page for page in self.pages.values() if page.get("parent_id") == str(parent_id)]
        return [deepcopy(page) for page in children[:limit]]

    def create_page(
        self,
        space,
        title,
        body,
        parent_id=None,
        type="page",
        representation="storage",
        editor=None,
        full_width=False,
        status="current",
    ):
        page_id = str(self._next_id)
        self._next_id += 1
        parent = self.pages[str(parent_id)]
        ancestors = [*parent.get("ancestors", []), {"id": str(parent_id), "title": parent["title"]}]
        page = _page(
            page_id, title, body, space=space, parent_id=str(parent_id), ancestors=ancestors
        )
        self.pages[page_id] = page
        self.create_calls.append(
            {
                "space": space,
                "title": title,
                "body": body,
                "parent_id": str(parent_id),
                "representation": representation,
            }
        )
        return deepcopy(page)

    def update_page(
        self,
        page_id,
        title,
        body=None,
        parent_id=None,
        type="page",
        representation="storage",
        minor_edit=False,
        version_comment=None,
        always_update=False,
        full_width=False,
    ):
        page = self.pages[str(page_id)]
        page["title"] = title
        page["body"]["storage"]["value"] = body
        self.update_calls.append(
            {
                "page_id": str(page_id),
                "title": title,
                "body": body,
                "version_comment": version_comment,
                "always_update": always_update,
            }
        )
        return deepcopy(page)

    def remove_page(self, page_id):
        self.remove_calls.append(str(page_id))
        self.pages.pop(str(page_id), None)


def _artifact_macro(
    section: str,
    content: str,
    ts: str = "2026-01-01T00:00:00",
) -> str:
    return (
        '<ac:structured-macro ac:name="panel">'
        f'<ac:parameter ac:name="title">{section}-{ts}</ac:parameter>'
        '<ac:parameter ac:name="aiyo-kind">artifact</ac:parameter>'
        f'<ac:parameter ac:name="aiyo-section">{section}</ac:parameter>'
        f'<ac:parameter ac:name="aiyo-ts">{ts}</ac:parameter>'
        f"<ac:rich-text-body><pre>{content}</pre></ac:rich-text-body>"
        "</ac:structured-macro>"
    )


def _new_store(
    root_body: str = "<p>root untouched</p>",
    child_title: str | None = None,
    child_body: str | None = None,
    extra_pages: list[dict] | None = None,
) -> tuple[ConfluenceArtifactStore, FakeConfluence]:
    pages = [_page("100", "MMAD - Memory - Artifact", root_body)]
    if child_title is not None:
        pages.append(
            _page(
                "300",
                child_title,
                child_body or "<p></p>",
                parent_id="100",
                ancestors=[{"id": "100", "title": "MMAD - Memory - Artifact"}],
            )
        )
    if extra_pages:
        pages.extend(extra_pages)
    client = FakeConfluence(pages)
    return ConfluenceArtifactStore(client, "100"), client


@pytest.mark.asyncio
async def test_upsert_artifact_creates_page_when_missing():
    store, client = _new_store()

    result = await store.upsert_artifact_section("PROJ-1", "smoke", "hello world")

    assert len(client.create_calls) == 1
    assert client.create_calls[0]["parent_id"] == "100"
    assert result["created_page"] is True
    assert result["page_id"] in client.pages
    child_body = client.pages[result["page_id"]]["body"]["storage"]["value"]
    assert 'ac:name="panel"' in child_body
    assert 'ac:name="aiyo-kind">artifact<' in child_body
    assert 'ac:name="aiyo-section">smoke<' in child_body
    assert "<ac:rich-text-body><pre>hello world</pre></ac:rich-text-body>" in child_body


@pytest.mark.asyncio
async def test_upsert_artifact_appends_section_on_existing_page():
    store, client = _new_store(child_title="PROJ-1", child_body=_artifact_macro("first", "one"))

    result = await store.upsert_artifact_section("PROJ-1", "second", "two")

    assert result["created_page"] is False
    assert result["updated"] is False
    assert result["row_index"] == 2
    child_body = client.pages["300"]["body"]["storage"]["value"]
    assert child_body.count('ac:name="aiyo-kind">artifact<') == 2


@pytest.mark.asyncio
async def test_upsert_artifact_replaces_matching_section_without_duplication():
    store, client = _new_store(child_title="PROJ-1", child_body=_artifact_macro("same", "one"))

    result = await store.upsert_artifact_section("PROJ-1", "same", "two")

    assert result["updated"] is True
    assert result["row_index"] == 1
    child_body = client.pages["300"]["body"]["storage"]["value"]
    assert child_body.count('ac:name="aiyo-kind">artifact<') == 1
    assert "<ac:rich-text-body><pre>one</pre></ac:rich-text-body>" not in child_body
    assert "<ac:rich-text-body><pre>two</pre></ac:rich-text-body>" in child_body


@pytest.mark.asyncio
async def test_get_artifact_returns_whole_page_mapping():
    store, _ = _new_store(
        child_title="PROJ-1",
        child_body=_artifact_macro("first", "one") + _artifact_macro("second", "two"),
    )

    result = await store.get_artifact("PROJ-1")

    assert result == {"first": "one", "second": "two"}


@pytest.mark.asyncio
async def test_get_artifact_returns_single_section_or_none():
    store, _ = _new_store(child_title="PROJ-1", child_body=_artifact_macro("first", "one"))

    assert await store.get_artifact("PROJ-1", "first") == "one"
    assert await store.get_artifact("PROJ-1", "missing") is None
    assert await store.get_artifact("MISSING") is None


@pytest.mark.asyncio
async def test_delete_artifact_with_section_only_removes_target_macro():
    store, client = _new_store(
        child_title="PROJ-1",
        child_body=_artifact_macro("first", "one") + _artifact_macro("second", "two"),
    )

    deleted = await store.delete_artifact("PROJ-1", "first")

    assert deleted is True
    assert await store.get_artifact("PROJ-1") == {"second": "two"}
    child_body = client.pages["300"]["body"]["storage"]["value"]
    assert 'ac:name="aiyo-section">first<' not in child_body
    assert 'ac:name="aiyo-section">second<' in child_body


@pytest.mark.asyncio
async def test_delete_artifact_removes_page():
    store, client = _new_store(child_title="PROJ-1", child_body=_artifact_macro("first", "one"))

    deleted = await store.delete_artifact("PROJ-1")

    assert deleted is True
    assert "300" not in client.pages
    assert client.remove_calls == ["300"]


@pytest.mark.asyncio
async def test_list_artifacts_is_scoped_to_root_children():
    external_page = _page("400", "PROJ-2", "<p>outside root</p>", parent_id="999", ancestors=[])
    store, _ = _new_store(
        child_title="PROJ-1",
        child_body=_artifact_macro("first", "one"),
        extra_pages=[external_page],
    )

    assert await store.list_artifacts() == ["PROJ-1"]


@pytest.mark.asyncio
async def test_list_artifacts_with_title_returns_section_titles():
    store, _ = _new_store(
        child_title="PROJ-1",
        child_body=_artifact_macro("first", "one") + _artifact_macro("second", "two"),
    )

    assert await store.list_artifacts("PROJ-1") == ["first", "second"]
    assert await store.list_artifacts("MISSING") == []


@pytest.mark.asyncio
async def test_get_artifact_ignores_same_title_page_outside_root():
    external_page = _page(
        "400",
        "PROJ-1",
        _artifact_macro("outside", "wrong"),
        parent_id="999",
        ancestors=[],
    )
    store, _ = _new_store(
        child_title="PROJ-1",
        child_body=_artifact_macro("inside", "right"),
        extra_pages=[external_page],
    )

    assert await store.get_artifact("PROJ-1") == {"inside": "right"}


@pytest.mark.asyncio
async def test_upsert_artifact_does_not_touch_root_page_body():
    store, client = _new_store(
        root_body="<p>root untouched</p>",
        child_title="PROJ-1",
        child_body="<p></p>",
    )

    await store.upsert_artifact_section("PROJ-1", "first", "one")

    assert client.pages["100"]["body"]["storage"]["value"] == "<p>root untouched</p>"


@pytest.mark.asyncio
async def test_pre_content_round_trips_with_xml_escaping():
    store, client = _new_store()

    result = await store.upsert_artifact_section("PROJ-1", "payload", 'a < b & "quoted"')

    body = client.pages[result["page_id"]]["body"]["storage"]["value"]
    assert "&lt;" in body
    assert "&amp;" in body
    assert await store.get_artifact("PROJ-1", "payload") == 'a < b & "quoted"'


@pytest.mark.asyncio
async def test_history_artifact_keeps_timestamped_panel_title_but_dedupes_by_original_title():
    store, client = _new_store(child_title="jira-history", child_body="<p></p>")

    await store.upsert_artifact_section("jira-history", "PROJ-1__decoder", "Decoder panic")

    body = client.pages["300"]["body"]["storage"]["value"]
    assert '<ac:parameter ac:name="aiyo-section">PROJ-1__decoder</ac:parameter>' in body
    assert "PROJ-1__decoder-20" in body


@pytest.mark.asyncio
async def test_upsert_dedupes_only_by_aiyo_section_metadata():
    store, client = _new_store(child_title="PROJ-1", child_body=_artifact_macro("legacy", "old"))

    result = await store.upsert_artifact_section("PROJ-1", "legacy", "new")

    assert result["updated"] is True
    body = client.pages["300"]["body"]["storage"]["value"]
    assert body.count('ac:name="aiyo-section">legacy<') == 1
    assert body.count('ac:name="aiyo-kind">artifact<') == 1
    assert "<ac:rich-text-body><pre>new</pre></ac:rich-text-body>" in body
    assert "<ac:rich-text-body><pre>old</pre></ac:rich-text-body>" not in body
