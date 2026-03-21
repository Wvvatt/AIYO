"""Tests for plan mode path restrictions."""


from aiyo.agent.middleware_plan import PlanModeMiddleware


def test_plan_mode_blocks_parent_traversal(monkeypatch, tmp_path):
    from aiyo.config import settings

    original_work_dir = settings.work_dir
    monkeypatch.setattr(settings, "work_dir", tmp_path)
    try:
        mw = PlanModeMiddleware()
        mw.toggle()
        allowed_name, allowed_args = mw.on_tool_call_start("write_file", {"path": ".plan/a.md"})
        assert allowed_name == "write_file"
        assert allowed_args["path"] == ".plan/a.md"

        blocked = False
        try:
            mw.on_tool_call_start("write_file", {"path": ".plan/../escape.md"})
        except Exception:
            blocked = True
        assert blocked
    finally:
        monkeypatch.setattr(settings, "work_dir", original_work_dir)


def test_plan_mode_blocks_symlink_escape(monkeypatch, tmp_path):
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

        mw = PlanModeMiddleware()
        mw.toggle()

        blocked = False
        try:
            mw.on_tool_call_start("edit_file", {"path": ".plan/out/evil.md"})
        except Exception:
            blocked = True
        assert blocked
    finally:
        monkeypatch.setattr(settings, "work_dir", original_work_dir)
