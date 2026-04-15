"""PDF reading tool for text extraction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._sandbox import safe_path
from .exceptions import ToolError
from .tool_meta import tool

logger = logging.getLogger(__name__)

_MAX_PDF_CHARS = 50000  # Maximum characters to extract from PDF


def _read_pdf_summary(tool_args: dict[str, object]) -> str:
    return str(tool_args.get("path", ""))


@tool(gatherable=True, summary=_read_pdf_summary)
async def read_pdf(path: str) -> dict[str, Any]:
    """Read a PDF file and extract text content.

    Extracts text from all pages of a PDF file for LLM analysis.
    Large PDFs are truncated to prevent excessive token usage.

    Maximum extracted content: 50000 characters

    Args:
        path: Path to the PDF file relative to workspace.

    Returns:
        Dict with PDF data:
        {
            "type": "pdf",
            "mime_type": "application/pdf",
            "path": "/path/to/doc.pdf",
            "content": "Extracted text content...",
            "pages": 42
        }

    Raises:
        ToolError: If file not found, invalid PDF, or unreadable.

    Examples:
        >>> result = await read_pdf("document.pdf")
        >>> result["type"]
        'pdf'
        >>> result["pages"]
        10
    """
    try:
        safe = safe_path(path)
        p = Path(safe)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not p.exists():
        raise ToolError(f"PDF file '{path}' not found.")
    if not p.is_file():
        raise ToolError(f"'{path}' is not a file.")

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        total_pages = len(reader.pages)

        # Extract text from all pages (with character limit)
        text_parts = []
        char_count = 0

        for page in reader.pages:
            page_text = page.extract_text() or ""
            if char_count + len(page_text) > _MAX_PDF_CHARS:
                remaining = _MAX_PDF_CHARS - char_count
                text_parts.append(page_text[:remaining])
                text_parts.append(f"\n[PDF text truncated at {_MAX_PDF_CHARS} characters]")
                break
            text_parts.append(page_text)
            char_count += len(page_text)

        text = "\n".join(text_parts)

        logger.debug(
            "Extracted PDF: %s (%d pages, %d chars)",
            p,
            total_pages,
            len(text),
        )

        return {
            "type": "pdf",
            "mime_type": "application/pdf",
            "path": str(p),
            "content": text,
            "pages": total_pages,
        }

    except ImportError as e:
        raise ToolError("PDF support requires pypdf package.") from e
    except PermissionError as e:
        raise ToolError(f"no read permission for '{path}'.") from e
    except Exception as e:
        raise ToolError(f"failed to read PDF: {e}") from e
