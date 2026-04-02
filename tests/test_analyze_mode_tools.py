"""Tests for ext.tools.analyze_mode_tools."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ext.tools.analyze_mode_tools import (
    AnalysisStructModel,
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


class TestAnalysisStructModel:
    def test_from_dict_normalizes_input(self):
        struct = AnalysisStructModel.model_validate(
            {
                "summary": " Decoder panic ",
                "root_cause": " invalid state transition ",
                "signals": "panic",
                "modules": [" decoder ", "", None],
                "fix": None,
                "evidence": [" stacktrace ", "   "],
            }
        )

        assert struct.summary == "Decoder panic"
        assert struct.root_cause == "invalid state transition"
        assert struct.signals == ["panic"]
        assert struct.modules == ["decoder"]
        assert struct.fix == ""
        assert struct.evidence == ["stacktrace"]


class TestExitAnalyze:
    async def test_exit_analyze_persists_struct_and_returns_report(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        issue_dir = tmp_path / ".jira-analysis" / "PROJ-1"
        issue_dir.mkdir(parents=True)

        with patch(
            "ext.tools.analyze_mode_tools._format_analysis_with_agent",
            return_value=(
                AnalysisStructModel(
                    summary="Decoder panic",
                    root_cause="Null state machine entered released path",
                    signals=["panic", "decoder exception"],
                    modules=["decoder"],
                    fix="Guard released state before flush",
                    evidence=["panic: decoder released twice"],
                ),
                {"source": "response_format", "warning": None, "raw_response": None},
            ),
        ):
            result = await exit_analyze(
                "proj-1",
                "Decoder panic caused by released state machine re-entering flush path.",
            )

        assert result["status"] == "ok"
        assert result["warnings"] == []
        assert (issue_dir / "analysis_struct.json").exists()
        assert result["analysis_struct"]["summary"] == "Decoder panic"
        assert "## Root Cause" in result["report_markdown"]
        assert result["formatter_source"] == "response_format"
        history_path = tmp_path / ".jira-analysis" / "history.jsonl"
        assert history_path.exists()
        assert history_path.read_text(encoding="utf-8").count("\n") == 1

    async def test_exit_analyze_skips_exact_duplicate_history(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        issue_dir = tmp_path / ".jira-analysis" / "PROJ-1"
        issue_dir.mkdir(parents=True)
        formatter_result = (
            AnalysisStructModel(
                summary="Decoder panic",
                root_cause="Null state machine entered released path",
                signals=["panic"],
                modules=["decoder"],
                fix="Guard released state before flush",
                evidence=["panic: decoder released twice"],
            ),
            {"source": "response_format", "warning": None, "raw_response": None},
        )

        with patch("ext.tools.analyze_mode_tools._format_analysis_with_agent", return_value=formatter_result):
            await exit_analyze("PROJ-1", "first conclusion")
            second = await exit_analyze("PROJ-1", "first conclusion")

        history_path = tmp_path / ".jira-analysis" / "history.jsonl"
        assert history_path.read_text(encoding="utf-8").count("\n") == 1
        assert any("Skipped appending history.jsonl" in warning for warning in second["warnings"])

    async def test_exit_analyze_returns_error_when_formatter_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        issue_dir = tmp_path / ".jira-analysis" / "PROJ-1"
        issue_dir.mkdir(parents=True)

        with patch(
            "ext.tools.analyze_mode_tools._format_analysis_with_agent",
            return_value=(None, {"source": "response_format_error", "warning": "format failed", "raw_response": None}),
        ):
            result = await exit_analyze("PROJ-1", "broken conclusion")

        assert result["status"] == "error"
        assert result["error_type"] == "parse_error"
        assert result["saved_files"] == []
        assert (issue_dir / "analysis_struct.json").exists() is False


class TestEnterAnalyze:
    async def test_enter_analyze_surfaces_degraded_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        jira = MagicMock()
        jira.issue.return_value = _mock_issue()
        creds = MagicMock()
        creds.client.return_value = jira
        creds.http_auth.return_value = ("user", "pass")

        with patch("ext.tools.analyze_mode_tools.JiraCredentials", return_value=creds):
            with patch(
                "ext.tools.analyze_mode_tools._download_attachments",
                return_value=([{"filename": "a.log", "status": "download_failed"}], [], ["boom"]),
            ):
                with patch(
                    "ext.tools.analyze_mode_tools._find_related_cases_with_agent",
                    return_value=([], {"source": "coarse_filter_fallback", "fallback_used": True, "warning": "fallback"}),
                ):
                    result = await enter_analyze("proj-1")

        assert result["issue_key"] == "PROJ-1"
        assert result["degraded"] is True
        assert "attachment_download_partial_failed" in result["degraded_flags"]
        assert "related_case_ranking_degraded" in result["degraded_flags"]
        assert result["related_cases_source"] == "coarse_filter_fallback"
        assert result["reference_analysis"] is None
        assert "boom" in result["warnings"]
        assert "fallback" in result["warnings"]
