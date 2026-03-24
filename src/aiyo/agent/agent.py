"""Core agent with tool-calling loop built on any-llm-sdk."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from any_llm import AnyLLM
from any_llm.exceptions import AnyLLMError, ContentFilterError
from any_llm.types.completion import ChatCompletionMessageToolCall

from aiyo.config import settings
from aiyo.tools import READ_TOOLS

from .exceptions import (
    AgentError,
    ContextFilterError,
    MaxIterationsError,
    ToolBlockedError,
)
from .history import HistoryManager
from .middleware_arg_normalization import ArgNormalizationMiddleware
from .middleware_base import MiddlewareChain
from .middleware_compaction import CompactionMiddleware
from .middleware_logging import LoggingMiddleware
from .middleware_plan import PlanModeMiddleware
from .middleware_stats import StatsMiddleware
from .middleware_vision import VisionMiddleware
from .stats import SessionStats

logger = logging.getLogger(__name__)


class Agent:
    """A tool-calling agent that maintains conversation history internally.

    The loop:
      1. Call LLM with the full history
      2. If the LLM requests tool calls → execute them, append results, go to 1
      3. If the LLM returns a plain message → append it to history, return it

    Features:
      - Comprehensive statistics tracking
      - Structured logging
      - Token-aware history management
      - Middleware support for extensibility
      - Enhanced error handling
      - Async interface
    """

    def __init__(
        self,
        system: str | None = None,
        model: str | None = None,
        extra_tools: list[Callable[..., Any]] | None = None,
        extra_middleware: list[Any] | None = None,
        max_history_tokens: int = 128000,
    ) -> None:
        """Initialize the Agent.

        Args:
            system: System prompt for the agent.
            model: Model name to use.
            extra_tools: Additional tools appended to the built-in READ_TOOLS (e.g. WRITE_TOOLS, EXT_TOOLS).
            extra_middleware: Additional Middleware instances to add after defaults.
            max_history_tokens: Maximum tokens in conversation history.
        """
        # Core LLM setup
        self._llm = AnyLLM.create(settings.provider)
        self._model = model or settings.model_name
        self._max_iterations = settings.agent_max_iterations

        # Vision middleware - detect capability at init
        self._vision_middleware = VisionMiddleware()
        self._vision_middleware.detect(self._llm, self._model)

        # Build system prompt: base + optional skill descriptions (Layer 1)
        from aiyo.tools.skills import get_skill_loader

        skill_desc = get_skill_loader().descriptions()

        self._system = f"""<system-reminder>
# System Instructions

{system or "You are a helpful AI assistant."}

## Tool Calling Rules (STRICT)

When you need to use a tool, you MUST use the standard OpenAI `tool_calls` format.
The response MUST include a `tool_calls` array, NOT XML in the content field.

### ✅ CORRECT format (MUST USE):
```json
{{
  "tool_calls": [
    {{
      "id": "call_xxx",
      "type": "function",
      "function": {{
        "name": "tool_name",
        "arguments": "{{\\"param\\": \\"value\\"}}"
      }}
    }}
  ]
}}
```

### ❌ INCORRECT format (NEVER USE):
```xml
<!-- DO NOT use this XML format in content! -->
<function_calls>
  <function_call>
    <invoke name="tool_name">
      <command>...</command>
      <args>{{...}}</args>
    </invoke>
  </function_call>
</function_calls>
```

### Guidelines

- If `tool_calls` is returned, keep `content` empty or only for thinking
- `tool_calls` array contains all tool calls to execute
- `function.arguments` is a JSON string, not an object

## Available Skills

Use `load_skill` to get full instructions for any skill:
- Skills are hierarchical.
- If you want to load a child skill, you MUST first load every parent skill above it in order from top to bottom.
- Never load a leaf or nested skill directly while skipping its parent skills.

{skill_desc if skill_desc else ""}

## Task Tool Strategy

- Use `task_create`, `task_update`, `task_get`, `task_list`, and `task_delete` to track multi-step work that spans multiple tool calls or needs explicit progress tracking.
- Prefer task tools over keeping ad-hoc TODO lists in free-form text when the work has multiple steps, dependencies, or status transitions.
- Before starting a substantial multi-step task, create a task or inspect existing tasks if task context is relevant.
- When a task result is returned as structured data, consume the JSON fields directly instead of relying on display formatting.
</system-reminder>"""

        # Tools setup: READ_TOOLS always built-in; extra_tools appended on top
        self._tools: list[Callable[..., Any]] = list(READ_TOOLS) + list(extra_tools or [])
        self._tool_map: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in self._tools}

        self._history = HistoryManager(
            max_tokens=max_history_tokens, model=self._model, llm=self._llm
        )
        self._stats = SessionStats()

        if self._system:
            self._history.add_message({"role": "system", "content": self._system})

        # Middleware
        self._middleware = MiddlewareChain()
        self._plan_middleware = PlanModeMiddleware()
        self._arg_normalization_middleware = ArgNormalizationMiddleware(tool_map=self._tool_map)

        # Add default middleware
        self._middleware.add(LoggingMiddleware()).add(StatsMiddleware(stats=self._stats)).add(
            CompactionMiddleware(history=self._history)
        ).add(self._vision_middleware).add(self._plan_middleware).add(
            self._arg_normalization_middleware
        )

        # Add extra middleware if provided
        if extra_middleware:
            for mw in extra_middleware:
                self._middleware.add(mw)

        logger.info(
            "Agent initialized with %d tools, model=%s, max_iterations=%d",
            len(self._tools),
            self._model,
            self._max_iterations,
        )

    # ===== Properties =====

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model

    @property
    def stats(self) -> SessionStats:
        """Get the SessionStats object."""
        return self._stats

    # ===== Public API =====

    async def chat(self, user_message: str) -> str:
        """Send a message and return the agent's reply.

        Conversation history is preserved across calls on the same instance.
        Call reset() to start a new conversation.

        Args:
            user_message: The user's message to process.

        Returns:
            The agent's text response.

        Raises:
            AgentError: For other agent-related errors.
        """
        user_message, tools = await self._middleware.execute_hook(
            "on_chat_start", user_message, self._tools
        )

        self._history.add_message({"role": "user", "content": user_message})

        # Run the agent loop
        try:
            response = await self._run_loop(tools)
        except MaxIterationsError as e:
            response = (
                f"Reached the maximum number of steps ({e.max_iterations}). "
                "The task may be too complex — try breaking it into smaller steps."
            )
        except asyncio.CancelledError:
            # Re-raise cancellation so callers (e.g., UI) can handle it
            raise
        except Exception as e:
            # Execute on_error middleware
            await self._middleware.execute_hook(
                "on_error", e, {"stage": "agent_loop", "user_message": user_message}
            )
            raise AgentError(f"Agent loop failed: {e}") from e

        # Execute on_chat_end middleware
        response = await self._middleware.execute_hook("on_chat_end", response)

        return response

    def reset(self) -> None:
        """Clear conversation history and start fresh.

        System prompt is preserved. Statistics are not reset.
        """
        self._history.clear()
        if self._system:
            self._history.add_message({"role": "system", "content": self._system})
        logger.info("Conversation history reset")

    def toggle_plan_mode(self) -> bool:
        """Toggle plan mode and return new state.

        Returns:
            True if plan mode is now active, False otherwise.
        """
        return self._plan_middleware.toggle()

    @property
    def plan_mode(self) -> bool:
        """Check if plan mode is active."""
        return self._plan_middleware.is_active

    async def compact(self, transcript_dir: Path | None = None) -> str:
        """Two-layer history compression.

        Delegates to HistoryManager.deep_compact().

        Returns:
            A human-readable status message.
        """
        return await self._history.deep_compact(transcript_dir or Path(".history"))

    def save_history(self) -> Path:
        """Save conversation history to <work_dir>/.history/.

        Returns:
            Path of the saved file.
        """
        from aiyo.config import settings

        return self._history.save(settings.work_dir)

    def get_history(self) -> list[dict[str, Any]]:
        """Get the current conversation history.

        Returns:
            List of message dictionaries.
        """
        return self._history.get_history()

    def get_history_summary(self) -> dict[str, Any]:
        """Get a summary of the conversation history.

        Returns:
            Dictionary with history statistics.
        """
        return self._history.get_summary()

    def print_stats(self) -> str:
        """Print a formatted statistics summary.

        Returns:
            Formatted statistics string.
        """
        return self._stats.format_report()

    def set_debug(self, debug: bool) -> None:
        """Enable or disable debug mode.

        Args:
            debug: Whether to enable debug mode.
        """
        if debug:
            logging.getLogger("aiyo").setLevel(logging.DEBUG)
        else:
            logging.getLogger("aiyo").setLevel(logging.INFO)

    # ===== Internal methods =====

    async def _run_loop(self, tools: list[Callable[..., Any]]) -> str:
        """Run the main agent loop.

        Args:
            tools: List of tools to use for this chat.

        Returns:
            The final text response from the LLM.

        Raises:
            MaxIterationsError: If max iterations is exceeded.
            asyncio.CancelledError: If operation was cancelled via task.cancel().
        """
        for iteration in range(self._max_iterations):
            logger.debug(
                "Iteration %d — %d messages in history",
                iteration + 1,
                len(self._history.get_history()),
            )

            # Execute on_iteration_start middleware
            messages = await self._middleware.execute_hook(
                "on_iteration_start", self._history.get_history()
            )

            # Execute LLM call
            response = await self._call_llm(messages, tools)
            assistant_msg = response.choices[0].message

            # If no tool calls, just add the assistant message and return
            if not assistant_msg.tool_calls:
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                }
                self._history.add_message(msg)
                return assistant_msg.content or ""

            # Execute all tool calls first (before adding anything to history)
            # in parallel. This allows cancellation without polluting history
            # with incomplete tool_calls, while reducing latency for independent calls.
            tool_calls = list(assistant_msg.tool_calls)
            results = await asyncio.gather(*(self._execute_tool(tc) for tc in tool_calls))
            message_pairs = [
                self._result_to_messages(tc.id, result)
                for tc, result in zip(tool_calls, results, strict=True)
            ]
            pending_tool_messages = [
                tool_msg for tool_msg, _ in message_pairs if tool_msg is not None
            ]
            pending_user_messages = [
                user_msg for _, user_msg in message_pairs if user_msg is not None
            ]

            # All tool calls completed successfully, now add to history
            # Build assistant message with tool_calls
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
            self._history.add_message(assistant_message)

            # Add all tool messages first, then user messages (OpenAI API requirement)
            for msg in pending_tool_messages:
                self._history.add_message(msg)
            for msg in pending_user_messages:
                self._history.add_message(msg)

            # Execute on_iteration_end middleware (after complete iteration including tool calls)
            await self._middleware.execute_hook(
                "on_iteration_end", iteration, self._history.get_history()
            )

        # Max iterations reached
        logger.warning("Agent reached max iterations (%d)", self._max_iterations)
        history = self._history.get_history()
        raise MaxIterationsError(
            max_iterations=self._max_iterations,
            last_response=history[-1].get("content") if history else None,
        )

    async def _call_llm(
        self, messages: list[dict[str, Any]], tools: list[Callable[..., Any]] | None = None
    ) -> Any:
        """Call the LLM with middleware hooks and error handling.

        Args:
            messages: The messages to send to the LLM.
            tools: Optional list of tools to use. Uses self._tools if not provided.

        Returns:
            The LLM response.

        Raises:
            TimeoutError: If LLM call times out.
            asyncio.CancelledError: If operation was cancelled.
            ContextFilterError: If content is blocked.
            AgentError: For other LLM errors.
        """
        tools = tools if tools is not None else self._tools
        try:
            async with asyncio.timeout(settings.llm_timeout):
                response = await self._llm.acompletion(
                    model=self._model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto",
                    max_tokens=settings.response_token_limit,
                )
        except TimeoutError as exc:
            logger.warning("LLM call timed out after %d seconds", settings.llm_timeout)
            raise AgentError(f"LLM call timed out after {settings.llm_timeout}s") from exc
        except ContentFilterError as exc:
            logger.warning("Content blocked by safety filter: %s", exc)
            raise ContextFilterError(str(exc)) from exc
        except AnyLLMError as exc:
            logger.error("LLM error: %s", exc)
            raise AgentError(f"LLM API error: {exc}") from exc

        # Execute on_llm_response middleware
        response = await self._middleware.execute_hook("on_llm_response", messages, response)

        return response

    async def _execute_tool(self, tool_call: ChatCompletionMessageToolCall) -> Any:
        """Execute a tool call with error handling and middleware hooks.

        Args:
            tool_call: The tool call object from the LLM.

        Returns:
            The tool's return value, or error message string if execution failed.
        """
        name = tool_call.function.name
        tool_id = tool_call.id

        try:
            parsed = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse tool arguments for '%s': %s", name, exc)
            return f"Error: invalid arguments JSON — {exc}"
        args = parsed if isinstance(parsed, dict) else {}

        # Execute on_tool_call_start middleware (may raise ToolBlockedError)
        try:
            name, tool_id, args = await self._middleware.execute_hook(
                "on_tool_call_start", name, tool_id, args
            )
        except ToolBlockedError as e:
            logger.info("Tool '%s' blocked by middleware: %s", name, e.reason)
            return e.reason

        fn = self._tool_map.get(name)
        if fn is None:
            logger.warning("Tool '%s' not registered", name)
            return f"Error: tool '{name}' is not available."

        tool_error: Exception | None = None
        try:
            result = await fn(**args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            tool_error = exc
            result = f"Error: tool '{name}' failed — {exc}"

        # Execute on_tool_call_end middleware
        result = await self._middleware.execute_hook(
            "on_tool_call_end", name, tool_id, args, tool_error, result
        )

        return result

    def _result_to_messages(
        self, tool_call_id: str, result: Any
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Convert tool result to structured messages for history.

        Handles multimodal content (images) by returning separate tool and user messages.
        Tool messages must be added to history before user messages (OpenAI API requirement).

        Args:
            tool_call_id: The ID of the tool call.
            result: The result from the tool execution.

        Returns:
            A tuple of (tool_message, user_message) where:
            - tool_message: The tool response message (None if no tool message needed)
            - user_message: Optional user message (e.g., for multimodal content)
        """
        # Handle image result from read_image
        # Tool messages cannot contain multimodal content, so we return:
        # 1. A tool message indicating the image was loaded
        # 2. A user message containing the actual image for the LLM to see
        if isinstance(result, dict) and result.get("type") == "image":
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"[Image loaded: {result['path']} ({result['size'] / 1024:.1f} KB)]",
            }
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here is the image:"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": result["content"],
                            "detail": "auto",
                        },
                    },
                ],
            }
            return tool_msg, user_msg

        # Handle PDF result from read_pdf
        if isinstance(result, dict) and result.get("type") == "pdf":
            text_content = (
                f"PDF file: {result['path']} ({result['pages']} pages)\n\n{result['content']}"
            )
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": text_content,
            }, None

        if isinstance(result, dict | list):
            try:
                serialized = json.dumps(result, ensure_ascii=False)
            except TypeError:
                serialized = str(result)
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": serialized,
            }, None

        # Default: single tool message, no user messages
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(result),
        }, None
