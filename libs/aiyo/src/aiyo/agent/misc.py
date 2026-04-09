"""Miscellaneous built-in middleware.

Groups three small, independent middleware that don't own any state worth
putting in its own module:

- ``LoggingMiddleware`` — structured debug logs for each hook
- ``ArgNormalizationMiddleware`` — coerce weak-model tool args to expected types
- ``VisionMiddleware`` — detect vision support and add ``use_ocr`` fallback
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from inspect import _empty, signature
from types import UnionType
from typing import Any, Union, get_args, get_origin

from .middleware import (
    ChatEndContext,
    ChatStartContext,
    ErrorContext,
    IterationStartContext,
    LLMResponseContext,
    Middleware,
    ToolCallEndContext,
    ToolCallStartContext,
)

logger = logging.getLogger(__name__)


# ===== LoggingMiddleware =====


class LoggingMiddleware(Middleware):
    """Structured and low-noise middleware logs."""

    _PREVIEW_LEN = 120

    def __init__(self) -> None:
        self.logger = logging.getLogger("aiyo.middleware.logging")

    @classmethod
    def _preview(cls, value: Any) -> str:
        text = str(value)
        if len(text) <= cls._PREVIEW_LEN:
            return text
        return text[: cls._PREVIEW_LEN] + "..."

    @staticmethod
    def _is_error_result(result: Any) -> bool:
        return isinstance(result, str) and result.startswith("Error:")

    @classmethod
    def _sanitize_args(cls, tool_args: dict[str, Any]) -> dict[str, Any]:
        # Keep log payload small and avoid leaking large/verbose values.
        return {k: cls._preview(v) for k, v in tool_args.items()}

    async def on_chat_start(self, ctx: ChatStartContext) -> None:
        self.logger.debug("chat.start tools=%d", len(ctx.tools))
        self.logger.debug("chat.input preview=%s", self._preview(ctx.user_message))

    async def on_chat_end(self, ctx: ChatEndContext) -> None:
        self.logger.debug("chat.end")
        self.logger.debug("chat.output preview=%s", self._preview(ctx.response))

    async def on_iteration_start(self, ctx: IterationStartContext) -> None:
        msg_count = len(ctx.messages)
        token_count = sum(len(str(m.get("content", ""))) for m in ctx.messages) // 4
        self.logger.debug("llm.call messages=%d approx_tokens=%d", msg_count, token_count)

    async def on_llm_response(self, ctx: LLMResponseContext) -> None:
        response = ctx.response
        msg = response.choices[0].message if hasattr(response, "choices") else response
        tool_calls = len(msg.tool_calls) if hasattr(msg, "tool_calls") and msg.tool_calls else 0
        self.logger.debug(
            "llm.response tool_calls=%d content_chars=%d", tool_calls, len(msg.content or "")
        )

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        self.logger.debug(
            "tool.start name=%s id=%s args=%s",
            ctx.tool_name,
            ctx.tool_id,
            self._sanitize_args(ctx.tool_args),
        )

    async def on_tool_call_end(self, ctx: ToolCallEndContext) -> None:
        status = (
            "error" if (ctx.tool_error is not None or self._is_error_result(ctx.result)) else "ok"
        )
        self.logger.debug(
            "tool.end name=%s id=%s status=%s error=%s result=%s",
            ctx.tool_name,
            ctx.tool_id,
            status,
            type(ctx.tool_error).__name__ if ctx.tool_error is not None else "-",
            self._preview(ctx.result),
        )

    async def on_error(self, ctx: ErrorContext) -> None:
        self.logger.debug(
            "error in %s: %s",
            ctx.context.get("stage", "unknown"),
            ctx.error,
            exc_info=True,
        )


# ===== ArgNormalizationMiddleware =====


def _expects_list(annotation: Any) -> bool:
    """Return True when the annotation is (or includes) a list type."""
    if annotation is _empty or annotation is Any:
        return False

    origin = get_origin(annotation)
    if origin is list:
        return True

    if origin in (UnionType, Union):
        return any(_expects_list(arg) for arg in get_args(annotation))

    return False


def _coerce_list_like(value: Any) -> Any:
    """Best-effort coercion for weak-model tool args: str -> list[str]."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return []

    # First try to parse JSON arrays represented as strings.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Fall back to common weak-model formats: comma/newline separated strings.
    if "," in stripped:
        return [part.strip() for part in stripped.split(",") if part.strip()]
    if "\n" in stripped:
        return [part.strip() for part in stripped.splitlines() if part.strip()]
    return [stripped]


class ArgNormalizationMiddleware(Middleware):
    """Normalize tool args before execution based on tool annotations."""

    def __init__(self, tool_map: dict[str, Callable[..., Any]]) -> None:
        self._tool_map = tool_map

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        fn = self._tool_map.get(ctx.tool_name)
        if fn is None:
            return

        try:
            sig = signature(fn)
        except Exception:
            return

        normalized = dict(ctx.tool_args)
        for param_name, param in sig.parameters.items():
            if param_name not in normalized:
                continue
            if _expects_list(param.annotation):
                normalized[param_name] = _coerce_list_like(normalized[param_name])

        ctx.tool_args = normalized


# ===== VisionMiddleware =====


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

    async def on_tool_call_start(self, ctx: ToolCallStartContext) -> None:
        """Add use_ocr parameter to read_image calls if needed."""
        if ctx.tool_name == "read_image" and self._supports_vision is False:
            ctx.tool_args = {**ctx.tool_args, "use_ocr": True}

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
