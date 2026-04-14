"""Skills loader: two-layer skill injection.

Layer 1 (cheap): skill names + descriptions surfaced in the system prompt.
Layer 2 (on demand): full SKILL.md body returned when the model calls load_skill().

Skills are loaded from multiple directories in priority order (highest wins on name clash):
    1. settings.work_dir / ".aiyo/skills"   (highest)
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

from ._markers import gatherable


class SkillValidationError(Exception):
    """Raised when a skill fails validation."""

    pass


# Cache configuration
_CACHE_DIR = Path.home() / ".cache" / "aiyo"
_CACHE_FILE = _CACHE_DIR / "skills_cache.json"
_CACHE_VERSION = 2  # Increment when cache format changes


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


@dataclass
class SkillNode:
    """A directory node in the skills tree, optionally backed by a skill."""

    name: str
    path: Path
    skill: Skill | None = None
    children: list[SkillNode] = field(default_factory=list)

    def get_child(self, name: str) -> SkillNode | None:
        """Return a child node by directory name."""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def get_or_create_child(self, name: str, path: Path) -> SkillNode:
        """Return or create a child node."""
        child = self.get_child(name)
        if child is None:
            child = SkillNode(name=name, path=path)
            self.children.append(child)
        return child


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


def _snapshot_skill_files(skill_dir: Path) -> dict[str, list[int]] | None:
    """Snapshot all files under a skill directory.

    Returns:
        Mapping of relative file path -> [mtime_ns, size].
        None when directory cannot be scanned due to permission errors.
    """
    snapshot: dict[str, list[int]] = {}
    try:
        for root, _subdirs, files in os.walk(skill_dir):
            root_path = Path(root)
            for name in files:
                file_path = root_path / name
                try:
                    stat = file_path.stat()
                except OSError:
                    return None
                rel = file_path.relative_to(skill_dir).as_posix()
                snapshot[rel] = [stat.st_mtime_ns, stat.st_size]
    except PermissionError:
        return None
    return snapshot


def _iter_cached_skill_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all cached skill entries under a serialized node tree."""
    entries: list[dict[str, Any]] = []
    skill_entry = node.get("skill")
    if isinstance(skill_entry, dict):
        entries.append(skill_entry)
    for child in node.get("children", []):
        if isinstance(child, dict):
            entries.extend(_iter_cached_skill_entries(child))
    return entries


def _is_cache_valid(cache: dict[str, Any], dirs: list[Path]) -> bool:
    """Check whether cache reflects current skill files and mtimes."""
    if cache.get("version") != _CACHE_VERSION:
        return False

    expected_dirs = {str(d.resolve()) for d in dirs if d.exists()}
    cached_dirs = set(cache.get("dirs", {}).keys())
    if expected_dirs != cached_dirs:
        return False

    cached_skills: dict[str, dict[str, Any]] = {}
    for root in cache.get("roots", []):
        if not isinstance(root, dict):
            return False
        for entry in _iter_cached_skill_entries(root):
            skill_path = entry.get("path")
            if not isinstance(skill_path, str):
                return False
            cached_skills[skill_path] = entry

    actual_paths: dict[str, int] = {}

    for d in dirs:
        if not d.exists():
            continue
        try:
            for root, _subdirs, files in os.walk(d):
                if "SKILL.md" in files:
                    skill_path = str((Path(root) / "SKILL.md").resolve())
                    actual_paths[skill_path] = Path(skill_path).stat().st_mtime_ns
        except PermissionError:
            continue

    if set(actual_paths.keys()) != set(cached_skills.keys()):
        return False

    for skill_path, mtime in actual_paths.items():
        cached_entry = cached_skills.get(skill_path, {})
        if cached_entry.get("mtime") != mtime:
            return False
        snapshot = _snapshot_skill_files(Path(skill_path).parent)
        if snapshot is None:
            return False
        if cached_entry.get("files") != snapshot:
            return False

    return True


class SkillLoader:
    """Scan one or more skills directories and expose Layer-1 + Layer-2 content.

    When multiple directories are given, pass them in descending priority order
    (highest first). Lower-priority directories only add skills not already defined.
    Uses file-based caching to avoid slow network filesystem reads.
    """

    def __init__(self, dirs: list[Path]) -> None:
        # name -> Skill
        self._skills: dict[str, Skill] = {}
        self._dirs = dirs
        self._roots: list[SkillNode] = []
        self._cache = _load_cache()
        self._cache_dirty = False

        # Check if we can use fast cached load.
        cache_valid = self._cache is not None and _is_cache_valid(self._cache, dirs)

        if cache_valid and self._cache:
            # Fast path: load all from cache (no filesystem access)
            self._load_from_cache()
        else:
            # Slow path: scan filesystem
            self._cache = {"version": _CACHE_VERSION, "roots": [], "dirs": {}}
            for d in dirs:
                self._load_dir(d)
            if self._cache_dirty:
                _save_cache(self._cache)

    def _load_from_cache(self) -> None:
        """Load all skills from cache without filesystem access."""
        for cached_root in self._cache.get("roots", []):
            try:
                root = self._node_from_cache(cached_root)
                self._roots.append(root)
                self._index_node_skills(root)
            except Exception:
                pass  # Skip corrupted cache entries

    def _load_dir(self, directory: Path) -> None:
        """Recursively load all skills from directory using parallel reads."""
        if not directory.exists():
            return

        root_path = directory.resolve()
        dir_key = str(root_path)
        root_node = SkillNode(name=directory.name or dir_key, path=root_path)
        self._roots.append(root_node)

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
        newest_mtime = 0

        def parse_skill_file(skill_file: Path) -> tuple[Path, Skill | None, int]:
            """Parse a single skill file, returning (path, skill, mtime)."""
            try:
                mtime = skill_file.stat().st_mtime_ns
                skill = self._parse_skill(skill_file)
                return skill_file, skill, mtime
            except Exception:
                return skill_file, None, 0

        # Use thread pool for parallel I/O on network filesystems
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = executor.map(parse_skill_file, skill_files)

        for skill_file, skill, mtime in results:
            if skill and skill.name not in self._skills:
                files_snapshot = _snapshot_skill_files(skill_file.parent)
                if files_snapshot is None:
                    continue
                self._skills[skill.name] = skill
                self._insert_skill_node(root_node, skill)
                newest_mtime = max(newest_mtime, mtime)
                self._cache_dirty = True

        self._cache["dirs"][dir_key] = newest_mtime
        self._cache["roots"].append(self._node_to_cache(root_node))

    def _index_node_skills(self, node: SkillNode) -> None:
        """Index all skills under a node by skill name."""
        if node.skill is not None:
            self._skills[node.skill.name] = node.skill
        for child in node.children:
            self._index_node_skills(child)

    def _insert_skill_node(self, root: SkillNode, skill: Skill) -> None:
        """Insert a skill into the directory node tree under a root."""
        relative_dir = skill.path.resolve().relative_to(root.path)
        current = root
        current_path = root.path
        for part in relative_dir.parts:
            current_path = current_path / part
            current = current.get_or_create_child(part, current_path)
        current.skill = skill

    @staticmethod
    def _skill_cache_entry(skill: Skill) -> dict[str, Any] | None:
        """Serialize a skill for cache storage."""
        files_snapshot = _snapshot_skill_files(skill.path)
        if files_snapshot is None:
            return None
        skill_file = skill.path / "SKILL.md"
        return {
            "path": str(skill_file.resolve()),
            "mtime": skill_file.stat().st_mtime_ns,
            "files": files_snapshot,
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

    def _node_to_cache(self, node: SkillNode) -> dict[str, Any]:
        """Serialize a node tree for cache storage."""
        cached: dict[str, Any] = {
            "name": node.name,
            "path": str(node.path.resolve()),
            "children": [self._node_to_cache(child) for child in sorted(node.children, key=lambda c: c.name)],
        }
        if node.skill is not None:
            cached_skill = self._skill_cache_entry(node.skill)
            if cached_skill is not None:
                cached["skill"] = cached_skill
        return cached

    def _node_from_cache(self, data: dict[str, Any]) -> SkillNode:
        """Deserialize a node tree from cache storage."""
        node = SkillNode(name=data["name"], path=Path(data["path"]))
        cached_skill = data.get("skill")
        if isinstance(cached_skill, dict):
            meta = SkillMeta(
                name=cached_skill["meta"]["name"],
                description=cached_skill["meta"]["description"],
                license=cached_skill["meta"].get("license"),
                compatibility=cached_skill["meta"].get("compatibility"),
                metadata=cached_skill["meta"].get("metadata", {}),
                allowed_tools=cached_skill["meta"].get("allowed_tools", []),
            )
            node.skill = Skill(
                meta=meta,
                body=cached_skill["body"],
                path=Path(cached_skill["path"]).parent,
            )
        node.children = [self._node_from_cache(child) for child in data.get("children", [])]
        return node

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
        """Layer 1: skill descriptions with directory hierarchy for the LLM."""
        return self.render_tree()

    def render_tree(self, max_description_len: int | None = None) -> str:
        """Render the skill node tree as text for prompts or CLI display."""
        if not self._roots:
            return ""

        lines: list[str] = []

        def format_description(description: str) -> str:
            if max_description_len is None or len(description) <= max_description_len:
                return description
            return f"{description[:max_description_len].rstrip()}..."

        def emit_node(node: SkillNode, depth: int) -> None:
            indent = "  " * depth
            if node.skill is not None:
                description = format_description(node.skill.description)
                lines.append(f"{indent}- skill: {node.skill.name} - {description}")
            else:
                lines.append(f"{indent}- dir: {node.name}/")

            for child in sorted(node.children, key=lambda item: item.name):
                emit_node(child, depth + 1)

        for root in self._roots:
            lines.append(f"- source: {root.path}")
            if root.skill is not None:
                description = format_description(root.skill.description)
                lines.append(f"  - skill: {root.skill.name} - {description}")
            for child in sorted(root.children, key=lambda item: item.name):
                emit_node(child, 1)

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

    def directory_tree(self) -> dict[str, Any]:
        """Return the directory hierarchy for all currently available skills."""
        def serialize(node: SkillNode, root_path: Path) -> dict[str, Any]:
            data: dict[str, Any] = {
                "name": node.name,
                "relative_path": node.path.resolve().relative_to(root_path).as_posix()
                if node.path.resolve() != root_path.resolve()
                else "",
                "children": [serialize(child, root_path) for child in sorted(node.children, key=lambda item: item.name)],
            }
            if node.skill is not None:
                data["skill"] = {
                    "name": node.skill.name,
                    "description": node.skill.description,
                    "relative_path": data["relative_path"],
                }
            return data

        return {
            "roots": [
                {
                    "name": root.name,
                    "path": str(root.path.resolve()),
                    "skill": (
                        {
                            "name": root.skill.name,
                            "description": root.skill.description,
                            "relative_path": "",
                        }
                        if root.skill is not None
                        else None
                    ),
                    "children": [serialize(child, root.path) for child in sorted(root.children, key=lambda item: item.name)],
                }
                for root in self._roots
            ]
        }


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
        1. work_dir / ".aiyo/skills"      (if work_dir provided, else cwd)
        2. Path.home() / ".aiyo/skills"
        3. skills_dir               (only included when explicitly set)

    Duplicate resolved paths are deduplicated; higher-priority entry is kept.
    """
    # Highest-priority first so dedup keeps the right one
    candidates: list[Path] = [
        (work_dir or Path.cwd()) / ".aiyo" / "skills",
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


@gatherable
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


@gatherable
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
