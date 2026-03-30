"""Tests for plan mode path restrictions."""

import pytest

from aiyo.agent.mode import AgentMode, ModeState, ToolsModeMiddleware


@pytest.mark.asyncio
async def test_plan_mode_blocks_parent_traversal(monkeypatch, tmp_path):
    from aiyo.config import settings

    original_work_dir = settings.work_dir
    monkeypatch.setattr(settings, "work_dir", tmp_path)
    try:
        state = ModeState()
        state.init(AgentMode.PLAN, [])
        mw = ToolsModeMiddleware(state=state)
        allowed_name, allowed_id, allowed_args = await mw.on_tool_call_start(
            "write_file", "call_1", {"path": ".plan/a.md"}
        )
        assert allowed_name == "write_file"
        assert allowed_id == "call_1"
        assert allowed_args["path"] == ".plan/a.md"

        blocked = False
        try:
            await mw.on_tool_call_start("write_file", "call_2", {"path": ".plan/../escape.md"})
        except Exception:
            blocked = True
        assert blocked
    finally:
        monkeypatch.setattr(settings, "work_dir", original_work_dir)


@pytest.mark.asyncio
async def test_plan_mode_blocks_symlink_escape(monkeypatch, tmp_path):
    from aiyo.config import settings

    original_work_dir = settings.work_dir
    monkeypatch.setattr(settings, "work_dir", tmp_path)
    try:
        (tmp_path / ".plan").mkdir()
        outside = tmp_path.parent / "plan-outside"
        outside.mkdir(exist_ok=True)
        link = tmp_path / ".plan" / "out"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            return  # symlink unsupported; skip-like behavior

        state = ModeState()
        state.init(AgentMode.PLAN, [])
        mw = ToolsModeMiddleware(state=state)

        blocked = False
        try:
            await mw.on_tool_call_start("edit_file", "call_3", {"path": ".plan/out/evil.md"})
        except Exception:
            blocked = True
        assert blocked
    finally:
        monkeypatch.setattr(settings, "work_dir", original_work_dir)
