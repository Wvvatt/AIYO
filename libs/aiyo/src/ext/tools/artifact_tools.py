"""Artifact store tools."""

from __future__ import annotations

from typing import Any

from aiyo.tools import tool
from aiyo.tools.exceptions import ToolError

from ext.artifact import ArtifactStore, get_artifact_store
from ext.config import ExtSettings
from ext.tools._health_cache import cached_health


async def health() -> dict[str, Any]:
    """Check artifact-store configuration health."""

    async def _probe() -> dict[str, Any]:
        cfg = ExtSettings()
        if not cfg.confluence_artifact_page_id:
            return {
                "name": "artifact_store",
                "status": "not_configured",
                "message": "CONFLUENCE_ARTIFACT_PAGE_ID missing",
            }

        try:
            get_artifact_store()
            return {
                "name": "artifact_store",
                "status": "ok",
                "message": cfg.confluence_artifact_page_id,
            }
        except Exception as exc:
            return {"name": "artifact_store", "status": "error", "message": str(exc)}

    return await cached_health("artifact_store", _probe)


def _artifact_store() -> ArtifactStore:
    try:
        return get_artifact_store()
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Failed to initialize artifact store: {exc}") from exc


def _field_summary(*names: str):
    def summary(tool_args: dict[str, Any]) -> str:
        return " ".join(str(tool_args.get(name)) for name in names if tool_args.get(name))

    return summary


@tool(gatherable=True, summary=_field_summary("title"), health_check=health)
async def list_artifacts(title: str = "") -> list[str]:
    """List artifact titles, or section titles when `title` is provided."""
    return await _artifact_store().list_artifacts(str(title or "").strip())


@tool(gatherable=True, summary=_field_summary("title", "section"), health_check=health)
async def get_artifact(title: str, section: str = "") -> dict[str, str] | str | None:
    """Get a whole artifact page or one named section from it."""
    title = str(title).strip()
    if not title:
        raise ToolError("title is required")
    return await _artifact_store().get_artifact(title, str(section or "").strip())


@tool(summary=_field_summary("title", "section"), health_check=health)
async def upsert_artifact_section(title: str, section: str, content: str) -> dict[str, Any]:
    """Create/update one artifact section on a page."""
    title = str(title).strip()
    if not title:
        raise ToolError("title is required")
    section = str(section).strip()
    if not section:
        raise ToolError("section is required")
    return await _artifact_store().upsert_artifact_section(title, section, content)


@tool(summary=_field_summary("title", "section"), health_check=health)
async def delete_artifact(title: str, section: str = "") -> bool:
    """Delete one artifact page by title, or delete one section when `section` is provided."""
    title = str(title).strip()
    if not title:
        raise ToolError("title is required")
    return await _artifact_store().delete_artifact(title, str(section or "").strip())


__all__ = [
    "list_artifacts",
    "get_artifact",
    "upsert_artifact_section",
    "delete_artifact",
]
