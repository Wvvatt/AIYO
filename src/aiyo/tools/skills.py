"""Skills loader: two-layer skill injection.

Layer 1 (cheap): skill names + descriptions surfaced in the system prompt.
Layer 2 (on demand): full SKILL.md body returned when the model calls load_skill().

Skills are loaded from multiple directories in priority order (highest wins on name clash):
    1. settings.work_dir / "skills"   (highest)
    2. Path.home()       / ".aiyo/skills"
    3. SKILLS_DIR        / "skills"   (lowest, only when set in .env)

Directory layout (per agentskills.io/specification):

    skill-name/
      ├── SKILL.md          # Required: metadata + instructions
      ├── scripts/          # Optional: executable code
      ├── references/       # Optional: documentation
      └── assets/           # Optional: templates, resources

SKILL.md format:
    ---
    name: skill-name              # Required: lowercase, hyphens, 1-64 chars
    description: "..."            # Required: 1-1024 chars
    license: "MIT"                # Optional: license name or file
    compatibility: "..."          # Optional: env requirements, max 500 chars
    metadata:                     # Optional: key-value mapping
      key1: value1
      key2: value2
    allowed-tools: "tool1 tool2"   # Optional: space-delimited tool list
    ---

    Markdown body with instructions...
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SkillValidationError(Exception):
    """Raised when a skill fails validation."""

    pass


# Cache configuration
_CACHE_DIR = Path.home() / ".cache" / "aiyo"
_CACHE_FILE = _CACHE_DIR / "skills_cache.json"
_CACHE_VERSION = 1  # Increment when cache format changes


@dataclass
class SkillMeta:
    """Parsed and validated skill metadata from frontmatter."""

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)

    # Validation constants per spec
    NAME_MAX_LEN = 64
    NAME_MIN_LEN = 1
    DESC_MAX_LEN = 1024
    DESC_MIN_LEN = 1
    COMPAT_MAX_LEN = 500

    def validate(self) -> None:
        """Validate all fields according to agentskills.io spec."""
        self._validate_name()
        self._validate_description()
        if self.compatibility is not None:
            self._validate_compatibility()

    def _validate_name(self) -> None:
        """Validate name field per spec:
        - 1-64 characters
        - lowercase letters, numbers, hyphens only
        - must not start or end with hyphen
        - must not contain consecutive hyphens
        """
        if not self.NAME_MIN_LEN <= len(self.name) <= self.NAME_MAX_LEN:
            raise SkillValidationError(
                f"Skill name must be {self.NAME_MIN_LEN}-{self.NAME_MAX_LEN} characters, "
                f"got {len(self.name)}: {self.name!r}"
            )

        if not re.match(r"^[a-z0-9-]+$", self.name):
            raise SkillValidationError(
                f"Skill name must contain only lowercase letters, numbers, and hyphens: "
                f"{self.name!r}"
            )

        if self.name.startswith("-") or self.name.endswith("-"):
            raise SkillValidationError(
                f"Skill name must not start or end with a hyphen: {self.name!r}"
            )

        if "--" in self.name:
            raise SkillValidationError(
                f"Skill name must not contain consecutive hyphens: {self.name!r}"
            )

    def _validate_description(self) -> None:
        """Validate description field per spec:
        - 1-1024 characters
        - non-empty
        """
        if not self.DESC_MIN_LEN <= len(self.description) <= self.DESC_MAX_LEN:
            raise SkillValidationError(
                f"Skill description must be {self.DESC_MIN_LEN}-{self.DESC_MAX_LEN} characters, "
                f"got {len(self.description)} for skill: {self.name!r}"
            )

    def _validate_compatibility(self) -> None:
        """Validate compatibility field per spec:
        - max 500 characters if provided
        """
        if self.compatibility and len(self.compatibility) > self.COMPAT_MAX_LEN:
            raise SkillValidationError(
                f"Skill compatibility must be max {self.COMPAT_MAX_LEN} characters, "
                f"got {len(self.compatibility)} for skill: {self.name!r}"
            )


@dataclass
class Skill:
    """A loaded skill with metadata, body, and directory path."""

    meta: SkillMeta
    body: str
    path: Path  # Path to the skill directory (parent of SKILL.md)

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def description(self) -> str:
        return self.meta.description

    def get_file(self, relative_path: str) -> Path | None:
        """Get a file path within the skill directory if it exists."""
        file_path = self.path / relative_path
        if file_path.exists() and file_path.is_file():
            return file_path
        return None

    def read_file(self, relative_path: str) -> str | None:
        """Read a file from the skill directory as text."""
        file_path = self.get_file(relative_path)
        if file_path is None:
            return None
        try:
            return file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


def _load_cache() -> dict[str, Any] | None:
    """Load skills cache from disk if valid."""
    try:
        if not _CACHE_FILE.exists():
            return None
        with open(_CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("version") != _CACHE_VERSION:
            return None
        return cache
    except Exception:
        return None


def _save_cache(cache: dict[str, Any]) -> None:
    """Save skills cache to disk."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Use compact JSON for faster I/O
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, separators=(",", ":"))
    except Exception:
        pass  # Cache failures are non-fatal


class SkillLoader:
    """Scan one or more skills directories and expose Layer-1 + Layer-2 content.

    When multiple directories are given, pass them in descending priority order
    (highest first). Lower-priority directories only add skills not already defined.
    Uses file-based caching to avoid slow network filesystem reads.
    """

    def __init__(self, dirs: list[Path]) -> None:
        # name -> Skill
        self._skills: dict[str, Skill] = {}
        self._cache = _load_cache()
        self._cache_dirty = False

        # Check if we can use fast cached load (compare dir count and cache age)
        cache_valid = self._cache is not None
        if cache_valid:
            # Simple check: ensure all directories still exist
            for d in dirs:
                if d.exists() and str(d.resolve()) not in self._cache.get("dirs", {}):
                    cache_valid = False
                    break

        if cache_valid and self._cache:
            # Fast path: load all from cache (no filesystem access)
            self._load_from_cache()
        else:
            # Slow path: scan filesystem
            self._cache = {"version": _CACHE_VERSION, "skills": {}, "dirs": {}}
            for d in dirs:
                self._load_dir(d)
            if self._cache_dirty:
                _save_cache(self._cache)

    def _load_from_cache(self) -> None:
        """Load all skills from cache without filesystem access."""
        for skill_path, cached in self._cache.get("skills", {}).items():
            try:
                meta = SkillMeta(
                    name=cached["meta"]["name"],
                    description=cached["meta"]["description"],
                    license=cached["meta"].get("license"),
                    compatibility=cached["meta"].get("compatibility"),
                    metadata=cached["meta"].get("metadata", {}),
                    allowed_tools=cached["meta"].get("allowed_tools", []),
                )
                skill = Skill(
                    meta=meta,
                    body=cached["body"],
                    path=Path(skill_path).parent,
                )
                self._skills[skill.name] = skill
            except Exception:
                pass  # Skip corrupted cache entries

    def _load_dir(self, directory: Path) -> None:
        """Recursively load all skills from directory using parallel reads."""
        if not directory.exists():
            return

        dir_key = str(directory.resolve())

        # First pass: collect all skill file paths
        skill_files: list[Path] = []
        try:
            for root, _dirs, files in os.walk(directory):
                if "SKILL.md" in files:
                    skill_files.append(Path(root) / "SKILL.md")
        except PermissionError:
            pass

        if not skill_files:
            self._cache["dirs"][dir_key] = 0.0
            return

        # Second pass: parse skills in parallel for network filesystems
        newest_mtime = 0.0

        def parse_skill_file(skill_file: Path) -> tuple[Path, Skill | None, float]:
            """Parse a single skill file, returning (path, skill, mtime)."""
            try:
                mtime = skill_file.stat().st_mtime
                skill = self._parse_skill(skill_file)
                return skill_file, skill, mtime
            except Exception:
                return skill_file, None, 0.0

        # Use thread pool for parallel I/O on network filesystems
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = executor.map(parse_skill_file, skill_files)

        for skill_file, skill, mtime in results:
            if skill and skill.name not in self._skills:
                self._skills[skill.name] = skill
                newest_mtime = max(newest_mtime, mtime)
                self._cache["skills"][str(skill_file.resolve())] = {
                    "mtime": mtime,
                    "meta": {
                        "name": skill.meta.name,
                        "description": skill.meta.description,
                        "license": skill.meta.license,
                        "compatibility": skill.meta.compatibility,
                        "metadata": skill.meta.metadata,
                        "allowed_tools": skill.meta.allowed_tools,
                    },
                    "body": skill.body,
                }
                self._cache_dirty = True

        self._cache["dirs"][dir_key] = newest_mtime

    def _parse_skill(self, skill_file: Path) -> Skill | None:
        """Parse a SKILL.md file into a Skill object."""
        text = skill_file.read_text(encoding="utf-8")
        meta_dict, body = _parse_frontmatter(text)

        # Use directory name as fallback for skill name
        name = meta_dict.get("name", skill_file.parent.name)

        # Required fields
        description = meta_dict.get("description", "")
        if not description:
            # Try to extract from body first heading
            desc_match = re.search(r"^#+\s*(.+)$", body, re.MULTILINE)
            description = desc_match.group(1) if desc_match else ""

        # Parse allowed-tools (space-delimited list)
        allowed_tools_str = meta_dict.get("allowed-tools", "")
        allowed_tools = allowed_tools_str.split() if allowed_tools_str else []

        # Parse metadata (nested dict)
        metadata = meta_dict.get("metadata", {})
        if isinstance(metadata, str):
            metadata = {}

        # Build SkillMeta
        skill_meta = SkillMeta(
            name=name,
            description=description,
            license=meta_dict.get("license"),
            compatibility=meta_dict.get("compatibility"),
            metadata=metadata,
            allowed_tools=allowed_tools,
        )

        skill_meta.validate()

        return Skill(
            meta=skill_meta,
            body=body,
            path=skill_file.parent,
        )

    def descriptions(self) -> str:
        """Layer 1: one-line descriptions for each skill (flat list for LLM)."""
        if not self._skills:
            return ""

        lines: list[str] = []
        for name in sorted(self._skills.keys()):
            skill = self._skills[name]
            lines.append(f"- {name}: {skill.description}")
        return "\n".join(lines)

    def content(self, name: str) -> str:
        """Layer 2: full SKILL.md body, wrapped in <skill> tags.

        Raises:
            SkillValidationError: If skill not found.
        """
        skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(sorted(self._skills)) or "(none)"
            raise SkillValidationError(f"Unknown skill '{name}'. Available: {available}")
        return f'<skill name="{name}">\n{skill.body}\n</skill>'

    def get_skill(self, name: str) -> Skill | None:
        """Get a Skill object by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all available skill names."""
        return sorted(self._skills.keys())


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from text.

    Supports:
    - Simple key: value pairs
    - Nested objects (metadata field)
    - Lists (converted to strings for simplicity)

    Returns:
        (metadata_dict, body)
    """
    # Match YAML frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text.strip()

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    # Parse simple YAML frontmatter
    meta = _parse_simple_yaml(frontmatter_text)

    return meta, body


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse a simple subset of YAML for frontmatter.

    Supports:
    - key: value (strings, numbers, bools)
    - key: | or > (multi-line strings)
    - Nested objects with 2-space indentation
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    current_key: str | None = None
    current_indent = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(stripped)

        # Check for multi-line string indicators
        if current_key is not None and indent > current_indent:
            # Continue multi-line string
            if isinstance(result.get(current_key), list):
                result[current_key].append(stripped)
            else:
                result[current_key] = result.get(current_key, "") + "\n" + stripped
            i += 1
            continue

        current_key = None
        current_indent = 0

        # Parse key: value
        if ":" in stripped:
            key, rest = stripped.split(":", 1)
            key = key.strip()
            value = rest.strip()

            # Check for multi-line indicators
            if value in ("|", ">", "|-", ">-"):
                # Multi-line string follows
                current_key = key
                current_indent = indent + 2
                result[key] = ""
                i += 1
                continue

            # Check for nested object start (empty value, next lines indented)
            if not value and i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.lstrip()
                next_indent = len(next_line) - len(next_stripped)
                if next_indent > indent and ":" in next_stripped:
                    # Nested object
                    nested_lines = []
                    j = i + 1
                    while j < len(lines):
                        nested_line = lines[j]
                        nested_stripped = nested_line.lstrip()
                        nested_indent = len(nested_line) - len(nested_stripped)
                        if nested_stripped and nested_indent <= indent:
                            break
                        if nested_stripped:
                            nested_lines.append(nested_line)
                        j += 1
                    result[key] = _parse_simple_yaml("\n".join(nested_lines))
                    i = j
                    continue

            # Parse value
            parsed_value = _parse_yaml_value(value)
            result[key] = parsed_value

        i += 1

    return result


def _parse_yaml_value(value: str) -> Any:
    """Parse a YAML scalar value."""
    value = value.strip()

    # Empty string
    if not value:
        return ""

    # Quoted strings
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    # Booleans
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False

    # Null
    if value.lower() in ("null", "~"):
        return None

    # Numbers
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # Default to string
    return value


def _resolve_dirs(work_dir: Path | None = None, skills_dir: Path | None = None) -> list[Path]:
    """Return skills directories in descending priority order (highest first).

    Priority (highest → lowest):
        1. work_dir / "skills"      (if work_dir provided, else cwd)
        2. Path.home() / ".aiyo/skills"
        3. skills_dir               (only included when explicitly set)

    Duplicate resolved paths are deduplicated; higher-priority entry is kept.
    """
    # Highest-priority first so dedup keeps the right one
    candidates: list[Path] = [
        (work_dir or Path.cwd()) / "skills",
        Path.home() / ".aiyo/skills",
    ]
    if skills_dir is not None:
        candidates.append(skills_dir)

    seen: set[Path] = set()
    unique: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    # Highest-priority first: SkillLoader skips skills already loaded
    return unique


# Module-level loader — populated lazily after settings are loaded.
_loader: SkillLoader | None = None


def get_skill_loader() -> SkillLoader:
    global _loader
    if _loader is None:
        # Delay import of settings to avoid slow startup
        try:
            from aiyo.config import settings

            work_dir = settings.work_dir
            skills_dir = settings.skills_dir
        except ImportError:
            work_dir = None
            skills_dir = None
        _loader = SkillLoader(_resolve_dirs(work_dir, skills_dir))
    return _loader


async def load_skill(name: str) -> str:
    """Load the full instructions for a named skill.

    Call this before tackling a task that matches one of the available skills.
    The skill body contains step-by-step guidance and examples.

    Args:
        name: The skill name (as listed in the system prompt).

    Raises:
        SkillValidationError: If skill not found.
    """
    loader = get_skill_loader()
    skill = loader.get_skill(name)
    if skill is None:
        available = ", ".join(sorted(loader.list_skills())) or "(none)"
        raise SkillValidationError(f"Unknown skill '{name}'. Available: {available}")
    return f'<skill name="{name}">\n{skill.body}\n</skill>'


async def load_skill_resource(skill_name: str, resource_path: str) -> str:
    """Load a resource file from a skill directory.

    Use this to access files in scripts/, references/, or assets/ subdirectories.

    Args:
        skill_name: The name of the skill.
        resource_path: Relative path from the skill directory (e.g., "references/guide.md").

    Raises:
        SkillValidationError: If skill not found or resource not found.
    """
    loader = get_skill_loader()
    skill = loader.get_skill(skill_name)
    if skill is None:
        available = ", ".join(loader.list_skills()) or "(none)"
        raise SkillValidationError(f"Unknown skill '{skill_name}'. Available: {available}")

    content = skill.read_file(resource_path)
    if content is None:
        raise SkillValidationError(f"Resource '{resource_path}' not found in skill '{skill_name}'.")

    return content
