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
    enter_analyze,
    exit_analyze,
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


class TestExitAnalyze:
    async def test_exit_analyze_derives_history_entry_and_cleans_issue_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ext.tools.analyze_tools.settings.work_dir", tmp_path)
        issue_dir = tmp_path / ".jira-analysis" / "PROJ-1" / "attachments"
        issue_dir.mkdir(parents=True)
        (issue_dir / "log.txt").write_text("hello", encoding="utf-8")

        history_entry = HistoryEntry(issue="PROJ-1", summary="Decoder panic", tags=["decoder"])

        with patch(
            "ext.tools.analyze_tools.HistoryEntry.from_conclusion",
            new=AsyncMock(return_value=history_entry),
        ) as from_conclusion:
            result = await exit_analyze("proj-1", "Short conclusion")

        from_conclusion.assert_awaited_once_with("PROJ-1", "Short conclusion")
        assert result == {
            "status": "ok",
            "issue_key": "PROJ-1",
            "summary": "Decoder panic",
            "tags": ["decoder"],
        }
        assert not (tmp_path / ".jira-analysis" / "PROJ-1").exists()

    async def test_exit_analyze_allows_missing_local_workspace(self):
        history_entry = HistoryEntry(issue="PROJ-1", summary="Decoder panic", tags=["decoder"])

        with patch(
            "ext.tools.analyze_tools.HistoryEntry.from_conclusion",
            new=AsyncMock(return_value=history_entry),
        ):
            result = await exit_analyze("proj-1", "Short conclusion")

        assert result["status"] == "ok"


class TestEnterAnalyze:
    async def test_enter_analyze_returns_issue_context(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("ext.tools.analyze_tools.settings.work_dir", tmp_path)

        jira = MagicMock()
        jira.issue.return_value = _mock_issue()
        creds = MagicMock()
        creds.client.return_value = jira
        creds.http_auth.return_value = ("user", "pass")
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
        assert Path(tmp_path / result["workspace"]).exists()
        assert set(result) == {
            "issue_key",
            "workspace",
            "summary",
            "description",
            "comments",
            "attachments",
            "warnings",
        }

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
        with patch("ext.tools.analyze_tools.JiraCredentials", return_value=creds):
            with patch(
                "ext.tools.analyze_tools._download_attachments",
                return_value=([], []),
            ):
                result = await enter_analyze("proj-1")

        workspace = tmp_path / result["workspace"]
        assert workspace.exists()
        assert not (workspace / "stale.txt").exists()
