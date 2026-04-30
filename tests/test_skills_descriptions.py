"""Tests for hierarchical skill descriptions."""

from aiyo.tools.skills import SkillLoader


def _write_skill(root, relative_dir: str, name: str, description: str) -> None:
    skill_dir = root / relative_dir
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_descriptions_include_directory_hierarchy(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "media/video/playback-skill", "playback-skill", "Playback flow")
    _write_skill(skills_root, "media/audio/mixer-skill", "mixer-skill", "Mixer flow")
    _write_skill(skills_root, "agent/review-skill", "review-skill", "Review flow")

    loader = SkillLoader([skills_root])

    assert loader.descriptions() == "\n".join(
        [
            f"- source: {skills_root.resolve()}",
            "  - dir: agent/",
            "    - skill: review-skill - Review flow",
            "  - dir: media/",
            "    - dir: audio/",
            "      - skill: mixer-skill - Mixer flow",
            "    - dir: video/",
            "      - skill: playback-skill - Playback flow",
        ]
    )


def test_descriptions_respect_loaded_skill_precedence(tmp_path):
    high_root = tmp_path / "high"
    low_root = tmp_path / "low"
    _write_skill(high_root, "media/shared-skill", "shared-skill", "High priority")
    _write_skill(low_root, "legacy/shared-skill", "shared-skill", "Low priority")
    _write_skill(low_root, "legacy/extra-skill", "extra-skill", "Extra skill")

    loader = SkillLoader([high_root, low_root])
    description = loader.descriptions()

    assert f"- source: {high_root.resolve()}" in description
    assert f"- source: {low_root.resolve()}" in description
    assert "skill: shared-skill - High priority" in description
    assert "skill: shared-skill - Low priority" not in description
    assert "skill: extra-skill - Extra skill" in description


def test_descriptions_support_parent_directories_that_are_also_skills(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "media-debug", "media-debug", "Top-level media triage")
    _write_skill(skills_root, "media-debug/video-debug", "video-debug", "Video triage")
    _write_skill(
        skills_root,
        "media-debug/video-debug/media-player/exoplayer-debug",
        "exoplayer-debug",
        "ExoPlayer triage",
    )

    description = SkillLoader([skills_root]).descriptions()

    assert "  - skill: media-debug - Top-level media triage" in description
    assert "    - skill: video-debug - Video triage" in description
    assert "      - dir: media-player/" in description
    assert "        - skill: exoplayer-debug - ExoPlayer triage" in description
    assert "dir: media-debug/" not in description
    assert "dir: video-debug/" not in description


def test_directory_tree_uses_node_shape(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "gerrit/gerrit-commit", "gerrit-commit", "Commit helper")
    _write_skill(skills_root, "gerrit/gerrit-review", "gerrit-review", "Review helper")

    tree = SkillLoader([skills_root]).directory_tree()
    root = tree["roots"][0]

    assert root["path"] == str(skills_root.resolve())
    assert root["skill"] is None
    assert root["children"][0]["name"] == "gerrit"
    assert root["children"][0]["children"][0]["skill"] == {
        "name": "gerrit-commit",
        "description": "Commit helper",
        "relative_path": "gerrit/gerrit-commit",
    }


def test_render_tree_can_truncate_descriptions(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "gerrit/gerrit-commit",
        "gerrit-commit",
        "Assist with committing code changes to Gerrit code review safely",
    )

    rendered = SkillLoader([skills_root]).render_tree(max_description_len=20)

    assert "skill: gerrit-commit - Assist with committi..." in rendered
