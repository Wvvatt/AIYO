"""Confluence storage XML helpers for artifact pages."""

from __future__ import annotations

from datetime import datetime

from aiyo.tools.exceptions import ToolError
from bs4 import BeautifulSoup, Tag

XML_ROOT = (
    '<root xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier">'
)
EMPTY_SECTION_BODY = "<p></p>"
MACRO_NAME = "panel"
SECTION_ARTIFACT = "artifact"
SECTION_PARAM = "aiyo-section"
TIMESTAMP_PARAM = "aiyo-ts"


def parse_storage(body: str) -> BeautifulSoup:
    """Parse storage-format XML under a synthetic root."""
    return BeautifulSoup(f"{XML_ROOT}{body}</root>", features="xml")


def serialize_storage(soup: BeautifulSoup) -> str:
    """Serialize synthetic-root XML back into Confluence storage."""
    root = soup.find("root")
    if root is None:
        raise ToolError("Confluence storage parsing failed: missing synthetic root.")
    return "".join(str(child) for child in root.contents)


def root_tag(soup: BeautifulSoup) -> Tag:
    """Return the synthetic root node."""
    root = soup.find("root")
    if root is None:
        raise ToolError("Confluence storage parsing failed: missing synthetic root.")
    return root


def macro_name(macro: Tag) -> str:
    """Return macro name across prefixed/non-prefixed XML parsers."""
    return str(macro.get("ac:name") or macro.get("name") or "")


def macro_param(macro: Tag, name: str) -> str:
    """Read one macro parameter."""
    for param in macro.find_all(["parameter", "ac:parameter"], recursive=False):
        if str(param.get("ac:name") or param.get("name") or "") == name:
            return param.get_text()
    return ""


def macro_body(macro: Tag) -> Tag | None:
    """Return a rich-text macro body if present."""
    return macro.find(["rich-text-body", "ac:rich-text-body"], recursive=False)


def artifact_section_title(macro: Tag) -> str:
    """Return the stable dedupe key for one artifact section."""
    return macro_param(macro, SECTION_PARAM)


def macro_sections(soup: BeautifulSoup, kind: str) -> list[Tag]:
    """List top-level macros of a specific kind."""
    sections: list[Tag] = []
    for child in root_tag(soup).find_all(recursive=False):
        if child.name not in {"structured-macro", "ac:structured-macro"}:
            continue
        if macro_name(child) != MACRO_NAME:
            continue
        if macro_param(child, "aiyo-kind") != kind:
            continue
        sections.append(child)
    return sections


def find_macro_by_param(
    soup: BeautifulSoup,
    kind: str,
    param_name: str,
    param_value: str,
) -> Tag | None:
    """Find the first macro where the named parameter matches."""
    for section in macro_sections(soup, kind):
        if macro_param(section, param_name) == param_value:
            return section
    return None


def macro_index_by_param(soup: BeautifulSoup, kind: str, param_name: str, param_value: str) -> int:
    """Return 1-based index of a macro among sections of the same kind."""
    for index, section in enumerate(macro_sections(soup, kind), start=1):
        if macro_param(section, param_name) == param_value:
            return index
    raise ToolError(
        f"Confluence artifact page is missing expected '{kind}' section '{param_value}'."
    )


def new_section_macro(
    soup: BeautifulSoup,
    kind: str,
    title: str,
    metadata: dict[str, str],
) -> tuple[Tag, Tag]:
    """Build a new macro with metadata and body."""
    macro = soup.new_tag("ac:structured-macro", attrs={"ac:name": MACRO_NAME})

    title_param = soup.new_tag("ac:parameter", attrs={"ac:name": "title"})
    title_param.string = title
    macro.append(title_param)

    kind_param = soup.new_tag("ac:parameter", attrs={"ac:name": "aiyo-kind"})
    kind_param.string = kind
    macro.append(kind_param)

    for key, value in metadata.items():
        param = soup.new_tag("ac:parameter", attrs={"ac:name": key})
        param.string = value
        macro.append(param)

    body = soup.new_tag("ac:rich-text-body")
    macro.append(body)
    return macro, body


def build_artifact_section(soup: BeautifulSoup, section: str, content: str) -> Tag:
    """Build an artifact macro whose stable key is stored in a macro parameter."""
    timestamp = datetime.now().isoformat()
    macro, body = new_section_macro(
        soup,
        SECTION_ARTIFACT,
        f"{section}-{timestamp}",
        {
            SECTION_PARAM: section,
            TIMESTAMP_PARAM: timestamp,
        },
    )
    block = soup.new_tag("pre")
    block.string = content
    body.append(block)
    return macro


def upsert_section(soup: BeautifulSoup, current_section: Tag | None, new_section: Tag) -> bool:
    """Replace one section or append it when absent."""
    if current_section is not None:
        current_section.replace_with(new_section)
        return True

    root_tag(soup).append(new_section)
    return False


def find_artifact_section(soup: BeautifulSoup, section: str) -> Tag | None:
    """Find one artifact section by its stable original title."""
    for artifact in macro_sections(soup, SECTION_ARTIFACT):
        if artifact_section_title(artifact) == section:
            return artifact
    return None


def artifact_section_index(soup: BeautifulSoup, section: str) -> int:
    """Return the 1-based index of one artifact section by stable original title."""
    for index, artifact in enumerate(macro_sections(soup, SECTION_ARTIFACT), start=1):
        if artifact_section_title(artifact) == section:
            return index
    raise ToolError(f"Confluence artifact page is missing expected section '{section}'.")


def list_artifact_sections(body: str) -> dict[str, str]:
    """Parse artifact storage into a section -> content mapping."""
    entries: dict[str, str] = {}
    soup = parse_storage(body)
    for section in macro_sections(soup, SECTION_ARTIFACT):
        content = ""
        body_tag = macro_body(section)
        block = body_tag.find("pre") if body_tag is not None else None
        if block is not None:
            content = block.get_text()
        entries[artifact_section_title(section)] = content
    return entries
