"""Artifact storage protocol for analyze mode."""

from __future__ import annotations

from typing import Any, Protocol


class ArtifactStore(Protocol):
    """Stable async interface for artifact CRUD operations."""

    async def list_artifacts(self, title: str = "") -> list[str]:
        """Return artifact titles, or section titles when one artifact title is provided."""

    async def get_artifact(
        self,
        title: str,
        section: str = "",
    ) -> dict[str, str] | str | None:
        """Return all sections for a page or one section when requested."""

    async def upsert_artifact_section(
        self,
        title: str,
        section: str,
        content: str,
    ) -> dict[str, Any]:
        """Create/update one artifact section on a page."""

    async def delete_artifact(self, title: str, section: str = "") -> bool:
        """Delete an artifact page, or one section when a section title is provided."""
