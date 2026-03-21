"""Tests for workspace sandbox path validation."""


import pytest

from aiyo.tools._sandbox import safe_path


@pytest.fixture
def temp_workspace(monkeypatch, tmp_path):
    from aiyo.config import settings

    original_work_dir = settings.work_dir
    monkeypatch.setattr(settings, "work_dir", tmp_path)
    yield tmp_path
    monkeypatch.setattr(settings, "work_dir", original_work_dir)


def test_safe_path_blocks_symlink_escape(temp_workspace):
    outside = temp_workspace.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    link = temp_workspace / "link-out"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not supported on this environment")

    with pytest.raises(ValueError, match="symlink"):
        safe_path("link-out/secret.txt")


def test_safe_path_allows_symlink_escape_when_explicit(temp_workspace):
    outside = temp_workspace.parent / "outside-target-2"
    outside.mkdir(exist_ok=True)
    link = temp_workspace / "link-out-allow"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not supported on this environment")

    resolved = safe_path("link-out-allow/secret.txt", allow_symlink_escape=True)
    assert str(resolved).startswith(str(outside))


def test_safe_path_blocks_parent_escape(temp_workspace):
    with pytest.raises(ValueError, match="Path escapes workspace"):
        safe_path("../outside.txt")
