"""Core agent with tool-calling loop built on any-llm-sdk."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from aiyo.config import settings
from aiyo.mcp import get_mcp_manager
from aiyo.tools import get_summary, is_gatherable
from any_llm import AnyLLM
from any_llm.exceptions import (
    AnyLLMError,
    ContentFilterError,
    ContextLengthExceededError,
    ProviderError,
    RateLimitError,
)
from any_llm.types.completion import ChatCompletionMessageToolCall

from .exceptions import (
    AgentError,
    ContextFilterError,
    MaxIterationsError,
    ToolBlockedError,
)
from .history import CompactionMiddleware, HistoryManager
from .middleware import (
    ChatEndContext,
    ChatStartContext,
    ErrorContext,
    IterationEndContext,
    IterationStartContext,
    LLMResponseContext,
    MiddlewareChain,
    ToolCallEndContext,
    ToolCallStartContext,
)
from .misc import ArgNormalizationMiddleware, LoggingMiddleware, VisionMiddleware
from .mode import AgentMode, ModeMiddleware, ModeState
from .stats import SessionStats, StatsMiddleware

logger = logging.getLogger(__name__)

_MAX_OUTPUT_RECOVERY = 3  # max "please continue" retries on length truncation
_MAX_RETRY_ATTEMPTS = 3  # max retries for transient LLM errors
_RETRY_BACKOFF = (1.0, 2.0, 4.0)  # seconds


def _assistant_message_to_history(message: Any) -> dict[str, Any]:
    """Serialize an SDK assistant message for replay in later LLM calls.

    Some providers require opaque assistant-side reasoning fields from prior
    turns to be echoed back verbatim when "thinking" mode is enabled. Avoid
    rebuilding assistant messages by hand so we do not drop provider-specific
    fields such as `reasoning`.
    """
    if hasattr(message, "model_dump"):
        data = message.model_dump(exclude_none=True)
    elif hasattr(message, "dict"):
        data = message.dict(exclude_none=True)
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data["role"] = "assistant"
    if "content" not in data:
        data["content"] = getattr(message, "content", "") or ""

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls and "tool_calls" not in data:
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]

    reasoning = getattr(message, "reasoning", None)
    reasoning_content = getattr(reasoning, "content", None)
    if isinstance(reasoning_content, str) and "reasoning" not in data:
        data["reasoning"] = {"content": reasoning_content}

    return data


def _read_agents_md(work_dir: Path) -> str:
    """Load AGENTS.md content from supported locations in priority order."""
    sections: list[str] = []
    for path in (
        Path.home() / ".aiyo" / "AGENTS.md",
        work_dir / ".aiyo" / "AGENTS.md",
        work_dir / "AGENTS.md",
    ):
        try:
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8").strip()
            else:
                content = ""
        except OSError:
            content = ""

        if content:
            sections.append(f"### {path}\n{content}")

    return "\n\n".join(sections)


def _render_workdir_tree(work_dir: Path, max_depth: int = 3) -> str:
    """Render a small tree-style snapshot of the work directory."""
    root = f"{work_dir.name or str(work_dir)}/"
    if not work_dir.is_dir():
        return root

    lines = [root]

    def walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower())
            )
        except OSError:
            return

        for index, entry in enumerate(entries):
            last = index == len(entries) - 1
            lines.append(
                f"{prefix}{'└── ' if last else '├── '}{entry.name}{'/' if entry.is_dir() else ''}"
            )
            if entry.is_dir():
                walk(entry, prefix + ("    " if last else "│   "), depth + 1)

    walk(work_dir, "", 0)
    return "\n".join(lines)


def _build_system_prompt(system: str | None = None) -> str:
    """Build the system prompt from dynamic environment context and instructions."""
    work_dir = settings.work_dir
    from aiyo.tools.skills import get_skill_loader

    now_str = datetime.now().astimezone().isoformat(timespec="seconds")
    work_dir_name = work_dir.name or str(work_dir)
    work_dir_tree = _render_workdir_tree(work_dir, max_depth=2)
    agents_md = _read_agents_md(work_dir)
    skill_descriptions = get_skill_loader().descriptions()

    prompt_sections = [
        "<system-reminder>",
        "# System Instructions",
        "",
        system or "You are a helpful AI assistant.",
        "",
        "## Runtime Context",
        "",
        f"- Time now: {now_str}",
        f"- Workdir name: {work_dir_name}",
        "",
        "### Workdir Tree",
        "",
        "```text",
        work_dir_tree,
        "```",
    ]

    prompt_sections.extend(
        [
            "",
            "## AGENTS Instructions",
            "",
            agents_md if agents_md else "",
        ]
    )

    prompt_sections.extend(
        [
            "## Available Skills",
            "",
            "Use `load_skill` to get full instructions for any skill:",
            "- Skills are hierarchical.",
            "- If you want to load a child skill, you MUST first load every parent skill above it in order from top to bottom.",
            "- Never load a leaf or nested skill directly while skipping its parent skills.",
            "",
            skill_descriptions if skill_descriptions else "",
            "</system-reminder>",
        ]
    )

    return "\n".join(prompt_sections)


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
        id: str | None = None,
        system: str | None = None,
        model: str | None = None,
        extra_tools: list[Callable[..., Any]] | None = None,
        exclude_tools: set[str] | None = None,
        mode: AgentMode = AgentMode.NORMAL,
        extra_middleware: list[Any] | None = None,
    ) -> None:
        """Initialize the Agent.

        Args:
            system: Optional override for the default top-level system instruction.
            model: Model name to use.
            extra_tools: Extra tools beyond BUILTIN_TOOLS (e.g. EXT_TOOLS).
            exclude_tools: Tool function names to exclude.
            mode: Initial tool access mode (NORMAL, PLAN).
            extra_middleware: Additional Middleware instances to add after defaults.
        """
        # Core LLM setup
        self.id = id or str(uuid.uuid4())[:8]
        self._llm = AnyLLM.create(settings.provider)
        self._model = model or settings.model_name
        self._max_iterations = settings.agent_max_iterations

        # Vision middleware - detect capability lazily on first chat
        self._vision_middleware = VisionMiddleware(self._model)

        # Build system prompt: base + optional skill descriptions (Layer 1)
        self.system_prompt = _build_system_prompt(system)

        # Full tool_map for execution lookup, never changes after construction.
        from aiyo.tools import BUILTIN_TOOLS  # noqa: PLC0415

        excluded = exclude_tools or set()
        tool_list = list(BUILTIN_TOOLS) + list(extra_tools or [])
        self._tools: list[Callable[..., Any]] = [
            fn for fn in tool_list if fn.__name__ not in excluded
        ]
        self._tool_map: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in self._tools}

        self._history = HistoryManager(
            max_tokens=settings.max_history_tokens, model=self._model, llm=self._llm
        )
        self._stats = SessionStats()

        if self.system_prompt:
            self._history.add_message({"role": "system", "content": self.system_prompt})

        # Middleware
        self._middleware = MiddlewareChain()
        self._mode_state = ModeState(mode=mode)
        self._mode_middleware = ModeMiddleware(state=self._mode_state)
        self._arg_normalization_middleware = ArgNormalizationMiddleware(tool_map=self._tool_map)

        # Add default middleware
        self._middleware.add(LoggingMiddleware()).add(StatsMiddleware(stats=self._stats)).add(
            CompactionMiddleware(history=self._history)
        ).add(self._vision_middleware).add(self._mode_middleware).add(
            self._arg_normalization_middleware
        )

        # Add extra middleware if provided
        if extra_middleware:
            for mw in extra_middleware:
                self._middleware.add(mw)

        logger.info(
            "[%s] Agent initialized with %d tools, model=%s, max_iterations=%d",
            self.id,
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
        await self._ensure_mcp_tools()

        chat_ctx = ChatStartContext(user_message=user_message, tools=self._tools)
        await self._middleware.execute_hook("on_chat_start", chat_ctx)
        user_message = chat_ctx.user_message
        tools = chat_ctx.tools

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
            err_ctx = ErrorContext(
                error=e, context={"stage": "agent_loop", "user_message": user_message}
            )
            await self._middleware.execute_hook("on_error", err_ctx)
            raise AgentError(f"Agent loop failed: {e}") from e

        # Execute on_chat_end middleware
        end_ctx = ChatEndContext(response=response)
        await self._middleware.execute_hook("on_chat_end", end_ctx)

        return end_ctx.response

    def reset(self) -> None:
        """Clear conversation history and start fresh.

        System prompt is preserved. Statistics are not reset.
        """
        self._history.clear()
        if self.system_prompt:
            self._history.add_message({"role": "system", "content": self.system_prompt})
        logger.info("Conversation history reset")

    @property
    def mode(self) -> AgentMode:
        """Current tool access mode."""
        return self._mode_state.mode

    def set_mode(self, mode: AgentMode) -> None:
        """Set the tool access mode."""
        self._mode_state.set(mode)

    async def compact(self, transcript_dir: Path | None = None) -> str:
        """Two-layer history compression.

        Delegates to HistoryManager.deep_compact().

        Returns:
            A human-readable status message.
        """
        return await self._history.deep_compact(transcript_dir or Path(".history"))

    def save_history(self) -> Path:
        """Save conversation history to <work_dir>/.history/."""
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

    async def _ensure_mcp_tools(self) -> None:
        """Load configured MCP tools once and add them to this agent."""
        mcp = get_mcp_manager()
        if not mcp.configured:
            return

        mcp_tools = await mcp.ensure_initialized()
        known = set(self._tool_map)
        added: list[Callable[..., Any]] = []
        for fn in mcp_tools:
            if fn.__name__ not in known:
                added.append(fn)
                known.add(fn.__name__)

        if added:
            self._tools.extend(added)
            self._tool_map.update({fn.__name__: fn for fn in added})

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
        output_recovery_attempts = 0

        for iteration in range(self._max_iterations):
            logger.debug(
                "Iteration %d — %d messages in history",
                iteration + 1,
                len(self._history.get_history()),
            )

            # Execute on_iteration_start middleware
            iter_start_ctx = IterationStartContext(messages=self._history.get_history())
            await self._middleware.execute_hook("on_iteration_start", iter_start_ctx)
            messages = iter_start_ctx.messages

            # Execute LLM call (with retry + context-too-long recovery)
            try:
                response = await self._call_llm(messages, tools)
            except ContextLengthExceededError:
                logger.warning("Context length exceeded; triggering compact and retrying")
                await self._history.deep_compact(Path(".history"))
                continue  # retry same iteration without consuming budget

            assistant_msg = response.choices[0].message

            # Handle max_tokens truncation: inject continuation prompt and retry
            if not assistant_msg.tool_calls:
                if (
                    response.choices[0].finish_reason == "length"
                    and output_recovery_attempts < _MAX_OUTPUT_RECOVERY
                ):
                    output_recovery_attempts += 1
                    logger.debug(
                        "Output truncated (length), requesting continuation (%d/%d)",
                        output_recovery_attempts,
                        _MAX_OUTPUT_RECOVERY,
                    )
                    self._history.add_message(_assistant_message_to_history(assistant_msg))
                    self._history.add_message(
                        {
                            "role": "user",
                            "content": "Please continue from where you left off.",
                        }
                    )
                    continue

                # Normal termination: add message and return
                output_recovery_attempts = 0
                msg = _assistant_message_to_history(assistant_msg)
                self._history.add_message(msg)
                return assistant_msg.content or ""

            output_recovery_attempts = 0

            # Execute all tool calls first (before adding anything to history)
            # Read-only tools run concurrently; mutation tools run serially.
            # Results are merged back in original order to preserve tool_call_id alignment.
            tool_calls = list(assistant_msg.tool_calls)
            results: list[Any] = [None] * len(tool_calls)

            gather_indices = [
                i
                for i, tc in enumerate(tool_calls)
                if is_gatherable(self._tool_map.get(tc.function.name))
            ]
            mutation_indices = [
                i
                for i, tc in enumerate(tool_calls)
                if not is_gatherable(self._tool_map.get(tc.function.name))
            ]

            if gather_indices:
                ro_results = await asyncio.gather(
                    *(self._execute_tool(tool_calls[i]) for i in gather_indices)
                )
                for idx, result in zip(gather_indices, ro_results):
                    results[idx] = result

            for i in mutation_indices:
                results[i] = await self._execute_tool(tool_calls[i])
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
            assistant_message = _assistant_message_to_history(assistant_msg)
            self._history.add_message(assistant_message)

            # Add all tool messages first, then user messages (OpenAI API requirement)
            for msg in pending_tool_messages:
                self._history.add_message(msg)
            for msg in pending_user_messages:
                self._history.add_message(msg)

            # Check iteration progress and add reminder at 30%, 60%, 90%
            thresholds = [0.3, 0.6, 0.9]
            for threshold in thresholds:
                target = int(self._max_iterations * threshold)
                if iteration + 1 == target and target > 0:
                    percentage = int(threshold * 100)
                    remaining = self._max_iterations - (iteration + 1)
                    self._history.add_message(
                        {
                            "role": "user",
                            "content": (
                                f"<system-reminder>Progress Notice: You have used {percentage}% "
                                f"of the available iteration budget ({iteration + 1}/{self._max_iterations} "
                                f"iterations). {remaining} iterations remaining. Please aim to complete "
                                f"the task or wrap up soon.</system-reminder>"
                            ),
                        }
                    )
                    break

            # Force summary at max_iterations - 1 (final chance to respond)
            if iteration + 1 == self._max_iterations - 1 and self._max_iterations > 1:
                self._history.add_message(
                    {
                        "role": "user",
                        "content": (
                            "<system-reminder>CRITICAL: This is your FINAL iteration. "
                            "You MUST NOT use any tools. Stop immediately and provide "
                            "a final summary of your progress and results to the user.</system-reminder>"
                        ),
                    }
                )

            # Execute on_iteration_end middleware (after complete iteration including tool calls)
            iter_end_ctx = IterationEndContext(
                iteration=iteration, messages=self._history.get_history()
            )
            await self._middleware.execute_hook("on_iteration_end", iter_end_ctx)

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

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                async with asyncio.timeout(settings.llm_timeout):
                    response = await self._llm.acompletion(
                        model=self._model,
                        messages=messages,
                        tools=tools if tools else None,
                        tool_choice="auto",
                        max_tokens=settings.response_token_limit,
                    )
                break  # success
            except TimeoutError as exc:
                logger.warning("LLM call timed out after %d seconds", settings.llm_timeout)
                raise AgentError(f"LLM call timed out after {settings.llm_timeout}s") from exc
            except ContentFilterError as exc:
                logger.warning("Content blocked by safety filter: %s", exc)
                raise ContextFilterError(str(exc)) from exc
            except ContextLengthExceededError:
                raise  # caller handles this
            except (RateLimitError, ProviderError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRY_ATTEMPTS - 1:
                    wait = _RETRY_BACKOFF[attempt]
                    logger.warning(
                        "Transient LLM error (%s), retrying in %.0fs (attempt %d/%d)",
                        type(exc).__name__,
                        wait,
                        attempt + 1,
                        _MAX_RETRY_ATTEMPTS,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error("LLM error after %d attempts: %s", _MAX_RETRY_ATTEMPTS, exc)
                raise AgentError(f"LLM API error: {exc}") from exc
            except AnyLLMError as exc:
                logger.error("LLM error: %s", exc)
                raise AgentError(f"LLM API error: {exc}") from exc
        else:
            raise AgentError(f"LLM API error after retries: {last_exc}") from last_exc

        # Execute on_llm_response middleware
        llm_ctx = LLMResponseContext(messages=messages, response=response)
        await self._middleware.execute_hook("on_llm_response", llm_ctx)

        return llm_ctx.response

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

        # Generate tool summary for display, preferring tool-local metadata.
        fn = self._tool_map.get(name)
        summary = get_summary(fn, args)

        # Execute on_tool_call_start middleware (may raise ToolBlockedError)
        start_ctx = ToolCallStartContext(
            tool_name=name, tool_id=tool_id, tool_args=args, summary=summary
        )
        try:
            await self._middleware.execute_hook("on_tool_call_start", start_ctx)
        except ToolBlockedError as e:
            logger.info("Tool '%s' blocked by middleware: %s", name, e.reason)
            return e.reason
        name = start_ctx.tool_name
        tool_id = start_ctx.tool_id
        args = start_ctx.tool_args
        summary = start_ctx.summary

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
        end_ctx = ToolCallEndContext(
            tool_name=name,
            tool_id=tool_id,
            tool_args=args,
            tool_error=tool_error,
            result=result,
        )
        await self._middleware.execute_hook("on_tool_call_end", end_ctx)

        return end_ctx.result

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
