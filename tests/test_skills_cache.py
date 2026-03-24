"""Tests for skills cache invalidation."""

from aiyo.tools.skills import _CACHE_VERSION, _is_cache_valid, _snapshot_skill_files


def test_skills_cache_invalidates_on_skill_file_change(tmp_path):
    skill_dir = tmp_path / "skills" / "demo-skill"
    references_dir = skill_dir / "references"
    skill_dir.mkdir(parents=True)
    references_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    ref_file = references_dir / "guide.md"
    skill_file.write_text(
        "---\nname: demo-skill\ndescription: demo\n---\n\nbody\n",
        encoding="utf-8",
    )
    ref_file.write_text("v1", encoding="utf-8")

    skill_path = str(skill_file.resolve())
    mtime = skill_file.stat().st_mtime_ns
    snapshot = _snapshot_skill_files(skill_dir)
    assert snapshot is not None

    cache = {
        "version": _CACHE_VERSION,
        "dirs": {str((tmp_path / "skills").resolve()): mtime},
        "roots": [
            {
                "name": "skills",
                "path": str((tmp_path / "skills").resolve()),
                "children": [
                    {
                        "name": "demo-skill",
                        "path": str(skill_dir.resolve()),
                        "children": [],
                        "skill": {
                            "path": skill_path,
                            "mtime": mtime,
                            "files": snapshot,
                            "meta": {"name": "demo-skill", "description": "demo"},
                            "body": "body",
                        },
                    }
                ],
            }
        ],
    }

    assert _is_cache_valid(cache, [tmp_path / "skills"])

    ref_file.write_text("v2", encoding="utf-8")

    assert not _is_cache_valid(cache, [tmp_path / "skills"])
