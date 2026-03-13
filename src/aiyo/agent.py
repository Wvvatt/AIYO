"""Core agent with tool-calling loop built on any-llm-sdk."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from any_llm import AnyLLM
from any_llm.exceptions import AnyLLMError, ContentFilterError

from .config import settings
from .exceptions import (
    AgentError,
    ContextFilterError,
    MaxIterationsError,
)
from .history import HistoryManager
from .middleware import LoggingMiddleware, MiddlewareChain, StatsMiddleware, TodoDisplayMiddleware
from .stats import AgentStats

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
    """

    def __init__(
        self,
        tools: list[Callable[..., Any]] | None = None,
        system: str | None = None,
        model: str | None = None,
        enable_stats: bool = True,
        enable_middleware: bool = True,
        max_history_tokens: int = 100000,
    ) -> None:
        """Initialize the Agent.

        Args:
            tools: List of tool functions available to the agent.
            system: System prompt for the agent.
            model: Model name to use.
            enable_stats: Whether to collect statistics.
            enable_middleware: Whether to enable default middleware.
            max_history_tokens: Maximum tokens in conversation history.
        """
        # Core LLM setup
        self._llm = AnyLLM.create(settings.provider)
        self._model = model or settings.model_name
        self._system = system or settings.agent_system_prompt
        self._max_iterations = settings.agent_max_iterations

        # Tools setup
        self._tools: list[Callable[..., Any]] = tools or []
        self._tool_map: dict[str, Callable[..., Any]] = {fn.__name__: fn for fn in self._tools}

        # History management
        self._history = HistoryManager(max_tokens=max_history_tokens, model=self._model)
        if self._system:
            self._history.add_message({"role": "system", "content": self._system})

        # Statistics
        self._stats = AgentStats() if enable_stats else None

        # Middleware
        self._middleware = MiddlewareChain()
        if enable_middleware:
            self._middleware.add(LoggingMiddleware()).add(StatsMiddleware()).add(
                TodoDisplayMiddleware()
            )

        # Debug mode
        self._debug = False

        logger.info(
            "Agent initialized with %d tools, model=%s, max_iterations=%d",
            len(self._tools),
            self._model,
            self._max_iterations,
        )

    def chat(self, user_message: str) -> str:
        """Send a message and return the agent's reply.

        Conversation history is preserved across calls on the same instance.
        Call reset() to start a new conversation.

        Args:
            user_message: The user's message to process.

        Returns:
            The agent's text response.

        Raises:
            MaxIterationsError: If max iterations is reached.
            AgentError: For other agent-related errors.
        """
        start_time = time.time()

        # Execute before_chat middleware
        user_message = self._middleware.execute_hook("before_chat", user_message)

        # Add user message to history
        self._history.add_message({"role": "user", "content": user_message})
        if self._stats:
            self._stats.record_user_message()

        # Run the agent loop
        try:
            response = self._run_loop()
        except MaxIterationsError:
            raise
        except Exception as e:
            # Execute on_error middleware
            self._middleware.execute_hook(
                "on_error", e, {"stage": "agent_loop", "user_message": user_message}
            )
            raise AgentError(f"Agent loop failed: {e}") from e

        # Execute after_chat middleware
        response = self._middleware.execute_hook("after_chat", response)

        # Record timing
        duration_ms = (time.time() - start_time) * 1000
        if self._stats:
            self._stats.record_assistant_message()
            self._stats.total_duration_ms += duration_ms

        return response

    def _run_loop(self) -> str:
        """Run the main agent loop.

        Returns:
            The final text response from the LLM.

        Raises:
            MaxIterationsError: If max iterations is exceeded.
        """
        history = self._history.get_history()

        for iteration in range(self._max_iterations):
            # Layer 1: shrink old tool results before every LLM call
            self._history.micro_compact()

            # Layer 2: LLM-summarize if still over token limit
            if (
                self._history.count_tokens(self._history.get_history())
                > self._history.effective_max
            ):
                logger.warning("Token limit exceeded, triggering auto compact")
                status = self.compact()
                logger.info("Auto compact: %s", status)

            history = self._history.get_history()

            logger.debug(
                "Iteration %d — %d messages in history",
                iteration + 1,
                len(history),
            )

            # Execute LLM call (with middleware hooks)
            response = self._call_llm(history)

            assistant_msg = response.choices[0].message

            # Build assistant message
            msg: dict[str, Any] = {"role": "assistant", "content": assistant_msg.content or ""}
            if assistant_msg.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ]

            # Add to history
            self._history.add_message(msg)
            history = self._history.get_history()

            # Execute iteration end middleware
            self._middleware.execute_hook("on_iteration_end", iteration, history)

            # Check if we need to make tool calls
            if not assistant_msg.tool_calls:
                return assistant_msg.content or ""

            # Execute all tool calls
            for tool_call in assistant_msg.tool_calls:
                result = self._execute_tool(tool_call)
                result_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                }
                self._history.add_message(result_msg)
                history = self._history.get_history()

        # Max iterations reached
        logger.warning("Agent reached max iterations (%d)", self._max_iterations)
        raise MaxIterationsError(
            max_iterations=self._max_iterations,
            last_response=history[-1].get("content") if history else None,
        )

    def _call_llm(self, messages: list[dict[str, Any]]) -> Any:
        """Call the LLM with middleware hooks and error handling.

        Args:
            messages: The message history to send.

        Returns:
            The LLM response.

        Raises:
            ContextFilterError: If content is blocked.
            AgentError: For other LLM errors.
        """
        # Execute before_llm_call middleware
        messages = self._middleware.execute_hook("before_llm_call", messages)

        try:
            response = self._llm.completion(
                model=self._model,
                messages=messages,
                tools=self._tools if self._tools else None,
                tool_choice="auto",
                max_tokens=settings.agent_max_tokens,
            )
        except ContentFilterError as exc:
            logger.warning("Content blocked by safety filter: %s", exc)
            raise ContextFilterError(str(exc)) from exc
        except AnyLLMError as exc:
            logger.error("LLM error: %s", exc)
            raise AgentError(f"LLM API error: {exc}") from exc

        # Execute after_llm_call middleware
        response = self._middleware.execute_hook("after_llm_call", messages, response)

        return response

    def reset(self) -> None:
        """Clear conversation history and start fresh.

        System prompt is preserved. Statistics are not reset.
        Use reset_stats() to clear statistics as well.
        """
        self._history.clear()
        if self._system:
            self._history.add_message({"role": "system", "content": self._system})
        logger.info("Conversation history reset")

    def print_stats(self) -> str:
        """Print a formatted statistics summary.

        Returns:
            Formatted statistics string.
        """
        if self._stats is None:
            return "Statistics are disabled."
        return self._stats.print_summary()

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

    def set_debug(self, debug: bool) -> None:
        """Enable or disable debug mode.

        Args:
            debug: Whether to enable debug mode.
        """
        self._debug = debug
        if debug:
            logging.getLogger("aiyo").setLevel(logging.DEBUG)
        else:
            logging.getLogger("aiyo").setLevel(logging.INFO)

    def _execute_tool(self, tool_call: Any) -> Any:
        """Execute a tool call with error handling and middleware hooks.

        Args:
            tool_call: The tool call object from the LLM.

        Returns:
            The tool's return value or error message.
        """
        name = tool_call.function.name

        # Parse arguments
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as exc:
            error_msg = f"Error: invalid arguments JSON — {exc}"
            logger.error("Failed to parse tool arguments for '%s': %s", name, exc)
            return error_msg

        # Check tool exists
        fn = self._tool_map.get(name)
        if fn is None:
            error_msg = f"Error: tool '{name}' is not available."
            logger.error("Tool '%s' not registered", name)
            return error_msg

        # Execute before_tool_call middleware
        name, args = self._middleware.execute_hook("before_tool_call", name, args)

        # Execute the tool
        print(f"\033[36mUsed\033[0m {name}")
        logger.debug("Calling tool '%s' with args %s", name, args)

        start_time = time.time()
        try:
            result = fn(**args)
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Tool '%s' completed in %.2fms",
                name,
                duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Error: tool '{name}' failed — {exc}"
            logger.error("Tool '%s' raised an exception after %.2fms: %s", name, duration_ms, exc)
            result = error_msg

        # Execute after_tool_call middleware
        result = self._middleware.execute_hook("after_tool_call", name, args, result)

        return result

    def compact(self, transcript_dir: Path | None = None) -> str:
        """Two-layer history compression.

        Delegates to HistoryManager.compact(), injecting the LLM summarizer.

        Returns:
            A human-readable status message.
        """

        def _summarize(conversation_text: str) -> str:
            response = self._llm.completion(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Summarize this conversation for continuity. Include: "
                            "1) What was accomplished, 2) Current state, "
                            "3) Key decisions made. "
                            "Be concise but preserve critical details.\n\n" + conversation_text
                        ),
                    }
                ],
                max_tokens=2000,
            )
            return response.choices[0].message.content or ""

        return self._history.deep_compact(_summarize, transcript_dir or Path(".history"))
