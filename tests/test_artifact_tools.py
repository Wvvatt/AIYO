"""Tests for ext.tools.artifact_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiyo.tools.exceptions import ToolError
from ext.tools import EXT_TOOLS
from ext.tools.artifact_tools import (
    delete_artifact,
    get_artifact,
    list_artifacts,
    upsert_artifact_section,
)


class TestArtifactTools:
    async def test_list_artifacts_routes_to_store(self):
        store = MagicMock()
        store.list_artifacts = AsyncMock(return_value=["PROJ-1", "COMMON-KB"])

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await list_artifacts()

        assert result == ["PROJ-1", "COMMON-KB"]
        store.list_artifacts.assert_awaited_once_with("")

    async def test_list_artifacts_with_title_routes_to_store(self):
        store = MagicMock()
        store.list_artifacts = AsyncMock(return_value=["jira", "gerrit"])

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await list_artifacts("PROJ-1")

        assert result == ["jira", "gerrit"]
        store.list_artifacts.assert_awaited_once_with("PROJ-1")

    async def test_get_artifact_routes_to_store(self):
        store = MagicMock()
        store.get_artifact = AsyncMock(return_value={"summary": "decoder crash"})

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await get_artifact("PROJ-1")

        assert result == {"summary": "decoder crash"}
        store.get_artifact.assert_awaited_once_with("PROJ-1", "")

    async def test_upsert_artifact_section_routes_to_store(self):
        store = MagicMock()
        store.upsert_artifact_section = AsyncMock(
            return_value={
                "page_id": "321",
                "page_url": "https://confluence.example.com/pages/viewpage.action?pageId=321",
                "row_index": 2,
                "updated": False,
                "created_page": True,
                "size": 5,
            }
        )

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await upsert_artifact_section("PROJ-1", "note1", "probe")

        assert result["page_id"] == "321"
        store.upsert_artifact_section.assert_awaited_once_with("PROJ-1", "note1", "probe")

    async def test_delete_artifact_routes_to_store(self):
        store = MagicMock()
        store.delete_artifact = AsyncMock(return_value=True)

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await delete_artifact("PROJ-1")

        assert result is True
        store.delete_artifact.assert_awaited_once_with("PROJ-1", "")

    async def test_delete_artifact_with_section_routes_to_store(self):
        store = MagicMock()
        store.delete_artifact = AsyncMock(return_value=False)

        with patch("ext.tools.artifact_tools._artifact_store", return_value=store):
            result = await delete_artifact("PROJ-1", "missing")

        assert result is False
        store.delete_artifact.assert_awaited_once_with("PROJ-1", "missing")

    async def test_missing_title_validation(self):
        with pytest.raises(ToolError, match="title is required"):
            await get_artifact("")

    async def test_missing_section_validation(self):
        with pytest.raises(ToolError, match="section is required"):
            await upsert_artifact_section("PROJ-1", "", "probe")


def test_artifact_tools_are_registered():
    tool_names = {tool_fn.__name__ for tool_fn in EXT_TOOLS}
    assert "list_artifacts" in tool_names
    assert "get_artifact" in tool_names
    assert "upsert_artifact_section" in tool_names
    assert "delete_artifact" in tool_names
