"""Tests for Confluence-backed analyze memory."""

from __future__ import annotations

from copy import deepcopy

from ext.infra.analyze_memory import ConfluenceMemory


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


def _new_memory(
    history_body: str, root_body: str, child_body: str | None = None
) -> tuple[ConfluenceMemory, FakeConfluence]:
    pages = [
        _page("100", "MMAD - Memory - Artifact", root_body),
        _page("200", "MMAD - Memory - History", history_body),
    ]
    if child_body is not None:
        pages.append(
            _page(
                "300",
                "MMAD - Memory - Artifact - TEST-1",
                child_body,
                parent_id="100",
                ancestors=[{"id": "100", "title": "MMAD - Memory - Artifact"}],
            )
        )
    client = FakeConfluence(pages)
    return ConfluenceMemory(client, "100", "200"), client


def test_upsert_history_renders_section():
    memory, client = _new_memory(
        "<p></p>",
        "<p></p>",
    )

    memory.upsert_history("TEST-1", "Decoder panic", ["decoder"])

    body = client.pages["200"]["body"]["storage"]["value"]
    assert 'ac:name="panel"' in body
    assert 'ac:name="aiyo-kind">history<' in body
    assert 'ac:name="aiyo-issue">TEST-1<' in body
    assert 'ac:name="aiyo-tags">decoder<' in body
    assert "<strong>Summary:</strong> Decoder panic" in body
    assert "<strong>Tags:</strong> decoder" in body
    assert "<pre>" not in body


def test_upsert_replaces_matching_row():
    memory, client = _new_memory(
        (
            '<ac:structured-macro ac:name="panel">'
            '<ac:parameter ac:name="title">TEST-1-2026-01-01T00:00:00</ac:parameter>'
            '<ac:parameter ac:name="aiyo-kind">history</ac:parameter>'
            '<ac:parameter ac:name="aiyo-issue">TEST-1</ac:parameter>'
            '<ac:parameter ac:name="aiyo-ts">2026-01-01T00:00:00</ac:parameter>'
            '<ac:parameter ac:name="aiyo-tags">decoder</ac:parameter>'
            "<ac:rich-text-body><p><strong>Summary:</strong> Old</p>"
            "<p><strong>Tags:</strong> decoder</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        ),
        "<p></p>",
    )

    memory.upsert_history("TEST-1", "New", ["codec"])

    body = client.pages["200"]["body"]["storage"]["value"]
    assert body.count('ac:name="aiyo-issue">TEST-1<') == 1
    assert 'ac:name="aiyo-tags">codec<' in body
    assert "<strong>Summary:</strong> New" in body
    assert "<strong>Summary:</strong> Old" not in body


def test_cdata_escape():
    memory, client = _new_memory(
        "<p></p>",
        "<p></p>",
    )

    memory.upsert_history("TEST-1", "Summary", ["decoder"])

    body = client.pages["200"]["body"]["storage"]["value"]
    assert "<pre>" not in body

    entries = memory.list_history()
    assert entries[0].summary == "Summary"


def test_upsert_artifact_creates_child_when_missing():
    memory, client = _new_memory(
        "<p></p>",
        "<p></p>",
    )

    result = memory.upsert_artifact("TEST-1", "smoke", "hello world")

    assert len(client.create_calls) == 1
    assert client.create_calls[0]["parent_id"] == "100"
    assert result["child_page_id"] in client.pages
    assert len(client.update_calls) == 1
    child_body = client.pages[result["child_page_id"]]["body"]["storage"]["value"]
    assert 'ac:name="aiyo-kind">artifact<' in child_body
    assert 'ac:name="aiyo-title">smoke<' in child_body
    assert "<pre>hello world</pre>" in child_body


def test_upsert_artifact_reuses_existing_child():
    memory, client = _new_memory(
        "<p></p>",
        "<p></p>",
    )

    first = memory.upsert_artifact("TEST-1", "first", "one")
    second = memory.upsert_artifact("TEST-1", "second", "two")

    assert len(client.create_calls) == 1
    assert first["child_page_id"] == second["child_page_id"]
    assert second["row_index"] == 2
    child_body = client.pages[first["child_page_id"]]["body"]["storage"]["value"]
    assert child_body.count('ac:name="aiyo-kind">artifact<') == 2


def test_upsert_artifact_replaces_matching_title():
    memory, client = _new_memory(
        "<p></p>",
        "<p></p>",
    )

    first = memory.upsert_artifact("TEST-1", "same", "one")
    second = memory.upsert_artifact("TEST-1", "same", "two")

    assert first["child_page_id"] == second["child_page_id"]
    assert second["updated"] is True
    assert second["row_index"] == 1
    child_body = client.pages[first["child_page_id"]]["body"]["storage"]["value"]
    assert child_body.count('ac:name="aiyo-kind">artifact<') == 1
    assert "<pre>one</pre>" not in child_body
    assert "<pre>two</pre>" in child_body


def test_upsert_artifact_does_not_touch_root_page_body():
    memory, client = _new_memory(
        "<p></p>",
        "<p>root untouched</p>",
        "<p></p>",
    )

    memory.upsert_artifact("TEST-1", "first", "one")

    root_body = client.pages["100"]["body"]["storage"]["value"]
    assert root_body == "<p>root untouched</p>"
