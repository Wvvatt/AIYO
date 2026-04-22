from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from aiyo.agent.agent import Agent, _build_system_prompt


def test_build_system_prompt_includes_agents_md_in_order(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    work_dir = tmp_path / "workspace"
    home_agents = home / ".aiyo" / "AGENTS.md"
    work_agents = work_dir / "AGENTS.md"
    src_dir = work_dir / "src"
    nested_dir = src_dir / "core"

    home_agents.parent.mkdir(parents=True)
    nested_dir.mkdir(parents=True)
    home_agents.write_text("home agents", encoding="utf-8")
    work_agents.write_text("work agents", encoding="utf-8")
    (work_dir / "README.md").write_text("readme", encoding="utf-8")
    (nested_dir / "main.py").write_text("print('ok')", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("aiyo.agent.agent.settings.work_dir", work_dir)
    mock_loader = MagicMock()
    mock_loader.descriptions.return_value = "- skill: demo - Demo skill"
    monkeypatch.setattr("aiyo.tools.skills.get_skill_loader", lambda: mock_loader)

    prompt = _build_system_prompt()

    assert "Time now:" in prompt
    assert "Workdir name: workspace" in prompt
    assert "### Workdir Tree" in prompt
    assert "workspace/" in prompt
    assert "src/" in prompt
    assert "core/" in prompt
    assert "main.py" in prompt
    assert "You are a helpful AI assistant." in prompt
    assert "home agents" in prompt
    assert "work agents" in prompt
    assert prompt.index("home agents") < prompt.index("work agents")
    assert "- skill: demo - Demo skill" in prompt


def test_build_system_prompt_accepts_custom_system(monkeypatch, tmp_path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    monkeypatch.setattr("aiyo.agent.agent.settings.work_dir", work_dir)
    mock_loader = MagicMock()
    mock_loader.descriptions.return_value = ""
    monkeypatch.setattr("aiyo.tools.skills.get_skill_loader", lambda: mock_loader)

    prompt = _build_system_prompt("custom system")

    assert "custom system" in prompt
    assert "You are a helpful AI assistant." not in prompt


def test_agent_uses_built_system_prompt(monkeypatch, tmp_path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    monkeypatch.setattr("aiyo.agent.agent.settings.work_dir", work_dir)

    with (
        patch("aiyo.agent.agent.AnyLLM") as agent_any_llm,
        patch("aiyo.agent.misc.VisionMiddleware.detect"),
        patch("aiyo.tools.skills.get_skill_loader") as get_skill_loader,
    ):
        agent_any_llm.create.return_value = MagicMock()
        get_skill_loader.return_value.descriptions.return_value = "- skill: alpha - desc"

        agent = Agent(system="custom system")

    assert "custom system" in agent.system_prompt
    assert "Workdir name: repo" in agent.system_prompt
    assert "- skill: alpha - desc" in agent.system_prompt
