"""Image reading tool for multimodal LLM input."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

from ._sandbox import safe_path
from .exceptions import ToolError

logger = logging.getLogger(__name__)

_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
_SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


async def read_image(path: str) -> dict[str, Any]:
    """Read an image file and return it for LLM analysis.

    Loads a local image file and returns it in a format suitable for
    multimodal LLMs (GPT-4o, Claude 3, etc.) to analyze.

    Supported formats: PNG, JPG, JPEG, GIF, WebP, BMP
    Maximum file size: 20MB

    Args:
        path: Path to the image file relative to workspace.

    Returns:
        Dict with image data:
        {
            "type": "image",
            "mime_type": "image/png",
            "path": "/path/to/image.png",
            "size": 12345,
            "content": "data:image/png;base64,iVBORw0KGgo..."
        }

    Raises:
        ToolError: If file not found, unsupported format, too large, or unreadable.

    Examples:
        >>> result = await read_image("screenshot.png")
        >>> result["type"]
        'image'
    """
    try:
        safe = safe_path(path)
        p = Path(safe)
    except ValueError as e:
        raise ToolError(str(e)) from e

    if not p.exists():
        raise ToolError(f"image file '{path}' not found.")
    if not p.is_file():
        raise ToolError(f"'{path}' is not a file.")

    ext = p.suffix.lower()
    if ext not in _SUPPORTED_IMAGE_FORMATS:
        supported = ", ".join(_SUPPORTED_IMAGE_FORMATS)
        raise ToolError(f"unsupported image format '{ext}'. Supported formats: {supported}")

    file_size = p.stat().st_size
    if file_size > _MAX_IMAGE_SIZE:
        raise ToolError(
            f"image file too large: {file_size / 1024 / 1024:.1f}MB "
            f"(max {_MAX_IMAGE_SIZE / 1024 / 1024:.0f}MB)"
        )

    try:
        data = p.read_bytes()
    except PermissionError as e:
        raise ToolError(f"no read permission for '{path}'.") from e

    mime_type, _ = mimetypes.guess_type(str(p))
    mime_type = mime_type or "image/png"

    encoded = base64.b64encode(data).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    logger.debug(
        "Loaded image: %s (%s, %.1fKB)",
        p,
        mime_type,
        file_size / 1024,
    )

    return {
        "type": "image",
        "mime_type": mime_type,
        "path": str(p),
        "size": file_size,
        "content": data_url,
    }
