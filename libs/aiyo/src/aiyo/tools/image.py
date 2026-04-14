"""Image reading tool for multimodal LLM input."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

from ._markers import gatherable
from ._sandbox import safe_path
from .exceptions import ToolError

logger = logging.getLogger(__name__)

_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
_SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@gatherable
async def read_image(path: str, use_ocr: bool = False) -> dict[str, Any]:
    """Read an image file for LLM analysis.

    For VLM-capable models: returns base64 image data.
    For non-VLM models (use_ocr=True): extracts text via OCR.

    Supported formats: PNG, JPG, JPEG, GIF, WebP, BMP
    Maximum file size: 20MB

    Args:
        path: Path to the image file relative to workspace.
        use_ocr: If True, use OCR instead of returning image data.

    Returns:
        Dict with image data:
        - type: "image" (base64) or "ocr" (text)
        - mime_type: MIME type
        - path: Absolute file path
        - size: File size in bytes
        - content: Base64 data URL or extracted text

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

    if use_ocr:
        return _read_with_ocr(p, file_size)

    return _read_as_base64(p, file_size)


def _read_as_base64(p: Path, file_size: int) -> dict[str, Any]:
    """Return image as base64 data URL for VLM models."""
    try:
        data = p.read_bytes()
    except PermissionError as e:
        raise ToolError(f"no read permission for '{p}'.") from e

    mime_type, _ = mimetypes.guess_type(str(p))
    mime_type = mime_type or "image/png"

    encoded = base64.b64encode(data).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    logger.debug("Loaded image: %s (%s, %.1fKB)", p, mime_type, file_size / 1024)

    return {
        "type": "image",
        "mime_type": mime_type,
        "path": str(p),
        "size": file_size,
        "content": data_url,
    }


def _read_with_ocr(p: Path, file_size: int) -> dict[str, Any]:
    """Extract text from image via OCR for non-VLM models."""
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(p)
        ocr_text = pytesseract.image_to_string(img).strip()

        if not ocr_text:
            ocr_text = "[No text detected in image]"

    except ImportError as e:
        raise ToolError(
            "OCR dependencies not installed. "
            "Install: pip install pytesseract pillow && ensure tesseract is available"
        ) from e
    except Exception as e:
        raise ToolError(f"OCR failed for '{p}': {e}") from e

    logger.debug("OCR extracted %d chars from %s", len(ocr_text), p)

    return {
        "type": "ocr",
        "mime_type": "text/plain",
        "path": str(p),
        "size": file_size,
        "content": ocr_text,
    }