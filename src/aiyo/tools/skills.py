"""Skills loader: two-layer skill injection.

Layer 1 (cheap): skill names + descriptions surfaced in the system prompt.
Layer 2 (on demand): full SKILL.md body returned when the model calls load_skill().

Skills are loaded from multiple directories in priority order (highest wins on name clash):
    1. settings.work_dir / "skills"   (highest)
    2. Path.home()       / "skills"
    3. SKILLS_DIR        / "skills"   (lowest, only when set in .env)

Directory layout:

    skills/
      pdf/
        SKILL.md    <- YAML frontmatter (name, description) + body
      code-review/
        SKILL.md
"""

from __future__ import annotations

import re
from pathlib import Path


class SkillLoader:
    """Scan one or more skills directories and expose Layer-1 + Layer-2 content.

    When multiple directories are given, pass them in ascending priority order
    (lowest first). Later entries overwrite earlier ones for the same skill name.
    """

    def __init__(self, dirs: list[Path]) -> None:
        # name -> {meta: dict, body: str}
        self._skills: dict[str, dict] = {}
        for d in dirs:
            self._load_dir(d)

    def _load_dir(self, directory: Path) -> None:
        if not directory.exists():
            return
        for skill_file in sorted(directory.rglob("SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", skill_file.parent.name)
            self._skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        """Layer 1: one-line descriptions for each skill (for the system prompt)."""
        if not self._skills:
            return ""
        lines = []
        for name, skill in self._skills.items():
            desc = skill["meta"].get("description", "")
            lines.append(f"  - {name}: {desc}" if desc else f"  - {name}")
        return "\n".join(lines)

    def content(self, name: str) -> str:
        """Layer 2: full SKILL.md body, wrapped in <skill> tags."""
        skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(self._skills) or "(none)"
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'

    def __bool__(self) -> bool:
        return bool(self._skills)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter (between --- delimiters) from body."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in match.group(1).strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta, match.group(2).strip()


def _resolve_dirs() -> list[Path]:
    """Return skills directories in ascending priority order (lowest first).

    Priority (highest → lowest):
        1. settings.work_dir / "skills"
        2. Path.home()       / "skills"
        3. settings.skills_dir            (only included when explicitly set)

    Duplicate resolved paths are deduplicated; higher-priority entry is kept.
    """
    from aiyo.config import settings

    # Highest-priority first so dedup keeps the right one
    candidates: list[Path] = [
        settings.work_dir / "skills",
        Path.home() / "skills",
    ]
    if settings.skills_dir is not None:
        candidates.append(settings.skills_dir)

    seen: set[Path] = set()
    unique: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    # Reverse so SkillLoader loads lowest-priority first (higher-priority overwrites)
    return list(reversed(unique))


# Module-level loader — populated lazily after settings are loaded.
_loader: SkillLoader | None = None


def _get_loader() -> SkillLoader:
    global _loader
    if _loader is None:
        _loader = SkillLoader(_resolve_dirs())
    return _loader


def get_skill_descriptions() -> str:
    """Return Layer-1 descriptions for injection into the system prompt."""
    return _get_loader().descriptions()


async def load_skill(name: str) -> str:
    """Load the full instructions for a named skill.

    Call this before tackling a task that matches one of the available skills.
    The skill body contains step-by-step guidance and examples.

    Args:
        name: The skill name (as listed in the system prompt).
    """
    return _get_loader().content(name)
