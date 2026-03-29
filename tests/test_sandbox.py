"""Tests for workspace path resolution."""

import pytest

from aiyo.tools._sandbox import safe_path


@pytest.fixture
def temp_workspace(monkeypatch, tmp_path):
    from aiyo.config import settings

    original_work_dir = settings.work_dir
    monkeypatch.setattr(settings, "work_dir", tmp_path)
    yield tmp_path
    monkeypatch.setattr(settings, "work_dir", original_work_dir)


def test_safe_path_resolves_relative(temp_workspace):
    result = safe_path("foo/bar.txt")
    assert result == temp_workspace / "foo" / "bar.txt"


def test_safe_path_resolves_absolute(temp_workspace):
    from pathlib import Path

    result = safe_path("/etc/passwd")
    assert result == Path("/etc/passwd").resolve()
