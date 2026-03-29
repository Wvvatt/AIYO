"""Middleware for vision capability handling."""

from __future__ import annotations

import logging
from typing import Any

from .middleware import Middleware

logger = logging.getLogger(__name__)


class VisionMiddleware(Middleware):
    """Middleware that handles vision capability for tools.

    When the model doesn't support vision, automatically adds use_ocr=True
    to read_image tool calls.
    """

    def __init__(self) -> None:
        self._supports_vision: bool | None = None

    def detect(self, llm: Any, model: str) -> None:
        """Detect if the model supports vision/image input.

        Sends a minimal test image and checks if the API accepts it.
        """
        test_msg = self._get_test_image_message()

        try:
            llm.completion(model=model, messages=[test_msg], max_tokens=10)
            self._supports_vision = True
            logger.info("Vision support: model supports images")
        except Exception as e:
            error_msg = str(e)
            if "20041" in error_msg or "not a vlm" in error_msg.lower():
                self._supports_vision = False
                logger.info("Vision support: model does NOT support images (will use OCR)")
            else:
                self._supports_vision = True
                logger.info("Vision detection error: %s", e)

    def on_tool_call_start(
        self, tool_name: str, tool_id: str, tool_args: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        """Add use_ocr parameter to read_image calls if needed."""
        if tool_name == "read_image" and self._supports_vision is False:
            tool_args = {**tool_args, "use_ocr": True}
        return tool_name, tool_id, tool_args

    @staticmethod
    def _get_test_image_message() -> dict[str, Any]:
        """Get a minimal test image message for vision capability detection."""
        # Minimal 1x1 transparent PNG
        test_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": "Test"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{test_image_b64}"},
                },
            ],
        }
