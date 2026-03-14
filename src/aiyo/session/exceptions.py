"""Custom exceptions for the AIYO agent."""

from typing import Any


class AgentError(Exception):
    """Base exception for all agent-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error message.
            details: Additional context about the error.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class MaxIterationsError(AgentError):
    """Raised when the agent reaches maximum iterations without a final answer."""

    def __init__(
        self,
        max_iterations: int,
        last_response: str | None = None,
    ) -> None:
        """Initialize the exception.

        Args:
            max_iterations: The maximum number of iterations allowed.
            last_response: The last response from the LLM, if any.
        """
        super().__init__(
            f"Agent reached maximum iterations ({max_iterations}) without a final answer",
            {"max_iterations": max_iterations, "last_response": last_response},
        )
        self.max_iterations = max_iterations
        self.last_response = last_response


class ContextFilterError(AgentError):
    """Raised when content is blocked by safety filters.

    This wraps the AnyLLM ContentFilterError for consistent handling.
    """

    def __init__(self, original_message: str) -> None:
        """Initialize the exception.

        Args:
            original_message: The original error message from the content filter.
        """
        super().__init__(f"Content blocked by safety filter: {original_message}")
        self.original_message = original_message
