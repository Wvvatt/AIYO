"""Tests for ext.tools.analyze_mode_tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiyo.tools.exceptions import ToolError
from ext.infra.analyze_models import HistoryEntry
from ext.tools.analyze_tools import (
    _get_jira_client,
    _get_memory,
    enter_analyze,
    exit_analyze,
    upsert_artifact,
)


def _mock_issue(
    key: str = "PROJ-1",
    summary: str = "Playback crash",
    description: str = "panic in decoder\nexception stack",
):
    fields = SimpleNamespace(
        summary=summary,
        description=description,
        status="Open",
        priority="Major",
        assignee="alice",
        reporter="bob",
        labels=["triage"],
        components=["Decoder"],
        updated="2026-04-02T10:00:00.000+0800",
        comment=SimpleNamespace(comments=[]),
        attachment=[],
    )
    return SimpleNamespace(key=key, fields=fields)


class TestClientBuilders:
    def test_get_jira_client_wraps_client_init_error(self):
        creds = MagicMock()
        creds.client.side_effect = RuntimeError("jira down")

        with patch("ext.tools.analyze_tools.JiraCredentials", return_value=creds):
            with pytest.raises(ToolError, match="Failed to initialize Jira client: jira down"):
                _get_jira_client()

    def test_get_memory_wraps_memory_init_error(self):
        client = MagicMock()

        with patch("ext.tools.analyze_tools.ConfluenceCredentials") as credentials_cls:
            credentials_cls.return_value.client.return_value = client
            with patch(
                "ext.tools.analyze_tools.ConfluenceMemory",
                side_effect=RuntimeError("memory broken"),
            ):
                with pytest.raises(
                    ToolError,
                    match="Failed to initialize Confluence memory: memory broken",
                ):
                    _get_memory()


class TestUpsertArtifact:
    async def test_upsert_artifact_routes_to_memory(self):
        memory = MagicMock()
        memory.upsert_artifact.return_value = {
            "child_page_id": "321",
            "child_page_url": "https://confluence.example.com/pages/viewpage.action?pageId=321",
            "row_index": 2,
            "updated": False,
        }

        with patch("ext.tools.analyze_tools._get_memory", return_value=memory):
            result = await upsert_artifact("proj-1", "note1", "probe")

        assert result == {
            "child_page_id": "321",
            "child_page_url": "https://confluence.example.com/pages/viewpage.action?pageId=321",
            "row_index": 2,
            "updated": False,
            "size": 5,
        }
        memory.upsert_artifact.assert_called_once_with("PROJ-1", "note1", "probe")


class TestExitAnalyze:
    async def test_exit_analyze_upserts_history_and_cleans_issue_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ext.tools.analyze_tools.settings.work_dir", tmp_path)
        issue_dir = tmp_path / ".jira-analysis" / "PROJ-1" / "attachments"
        issue_dir.mkdir(parents=True)
        (issue_dir / "log.txt").write_text("hello", encoding="utf-8")

        memory = MagicMock()
        memory.history_page_id = "200"
        history_entry = HistoryEntry(issue="PROJ-1", summary="Decoder panic", tags=["decoder"])

        with patch("ext.tools.analyze_tools._get_memory", return_value=memory):
            with patch(
                "ext.tools.analyze_tools.HistoryEntry.from_conclusion",
                new=AsyncMock(return_value=history_entry),
            ):
                result = await exit_analyze("proj-1", "Short conclusion")

        memory.upsert_history.assert_called_once_with("PROJ-1", "Decoder panic", ["decoder"])
        assert result == {
            "status": "ok",
            "issue_key": "PROJ-1",
            "summary": "Decoder panic",
            "tags": ["decoder"],
            "history_page_id": "200",
        }
        assert not (tmp_path / ".jira-analysis" / "PROJ-1").exists()

    async def test_exit_analyze_allows_missing_local_workspace(self):
        memory = MagicMock()
        memory.history_page_id = "200"
        history_entry = HistoryEntry(issue="PROJ-1", summary="Decoder panic", tags=["decoder"])

        with patch("ext.tools.analyze_tools._get_memory", return_value=memory):
            with patch(
                "ext.tools.analyze_tools.HistoryEntry.from_conclusion",
                new=AsyncMock(return_value=history_entry),
            ):
                result = await exit_analyze("proj-1", "Short conclusion")

        assert result["status"] == "ok"
        memory.upsert_history.assert_called_once()


class TestEnterAnalyze:
    async def test_enter_analyze_writes_history_cache_and_dedupes_artifacts(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ext.tools.analyze_tools.settings.work_dir", tmp_path)

        jira = MagicMock()
        jira.issue.return_value = _mock_issue()
        creds = MagicMock()
        creds.client.return_value = jira
        creds.http_auth.return_value = ("user", "pass")
        memory = MagicMock()
        memory.history_page_id = "200"
        memory.client.get_page_by_id.return_value = {
            "body": {"storage": {"value": "<p>Old case</p><p>decoder</p>"}}
        }
        memory.get_artifact_page_storage.return_value = {
            "page_id": "321",
            "page_url": "https://confluence.example.com/pages/viewpage.action?pageId=321",
            "content": "<xml>artifact page</xml>",
        }

        with patch("ext.tools.analyze_tools._get_memory", return_value=memory):
            with patch("ext.tools.analyze_tools.JiraCredentials", return_value=creds):
                with patch(
                    "ext.tools.analyze_tools._download_attachments",
                    return_value=(
                        [{"filename": "a.log", "status": "download_failed"}],
                        ["boom"],
                    ),
                ):
                    result = await enter_analyze("proj-1")

        assert result["issue_key"] == "PROJ-1"
        assert "boom" in result["warnings"]
        history_path = tmp_path / result["history_path"]
        artifacts_path = tmp_path / result["artifacts_path"]
        assert history_path.exists()
        assert artifacts_path.exists()
        assert history_path.name == "history.xml"
        assert artifacts_path.name == "artifacts.xml"
        assert "<p>Old case</p>" in history_path.read_text(encoding="utf-8")
        assert "<xml>artifact page</xml>" in artifacts_path.read_text(encoding="utf-8")
        assert Path(tmp_path / result["workspace"]).exists()

    async def test_enter_analyze_clears_stale_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ext.tools.analyze_tools.settings.work_dir", tmp_path)

        stale_dir = tmp_path / ".jira-analysis" / "PROJ-1"
        stale_dir.mkdir(parents=True)
        (stale_dir / "stale.txt").write_text("old", encoding="utf-8")

        jira = MagicMock()
        jira.issue.return_value = _mock_issue()
        creds = MagicMock()
        creds.client.return_value = jira
        creds.http_auth.return_value = ("user", "pass")

        memory = MagicMock()
        memory.history_page_id = "200"
        memory.client.get_page_by_id.return_value = {
            "body": {"storage": {"value": "<p>Old case</p>"}}
        }
        memory.get_artifact_page_storage.return_value = None

        with patch("ext.tools.analyze_tools._get_memory", return_value=memory):
            with patch("ext.tools.analyze_tools.JiraCredentials", return_value=creds):
                with patch(
                    "ext.tools.analyze_tools._download_attachments",
                    return_value=([], []),
                ):
                    result = await enter_analyze("proj-1")

        workspace = tmp_path / result["workspace"]
        assert workspace.exists()
        assert not (workspace / "stale.txt").exists()
