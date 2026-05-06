"""Artifact store factory."""

from __future__ import annotations

from aiyo.tools.exceptions import ToolError

from ext.config import ExtSettings
from ext.infra.credentials import ConfluenceCredentials

from .confluence_store import ConfluenceArtifactStore
from .protocol import ArtifactStore


def get_artifact_store() -> ArtifactStore:
    """Build the configured artifact store for analyze mode."""
    cfg = ExtSettings()
    if not cfg.confluence_artifact_page_id:
        raise ToolError("CONFLUENCE_ARTIFACT_PAGE_ID must be configured for analyze-mode memory.")

    try:
        client = ConfluenceCredentials().client()
    except KeyError as exc:
        raise ToolError(f"Confluence credentials not configured: {exc}") from exc
    except Exception as exc:
        raise ToolError(f"Failed to initialize Confluence client: {exc}") from exc

    try:
        return ConfluenceArtifactStore(
            client=client,
            artifact_root_page_id=cfg.confluence_artifact_page_id,
        )
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Failed to initialize artifact store: {exc}") from exc
