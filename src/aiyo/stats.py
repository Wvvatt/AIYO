"""Statistics tracking for the AIYO agent."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ToolExecutionStats:
    """Statistics for a single tool execution."""

    name: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        """Average duration per call in milliseconds."""
        if self.calls == 0:
            return 0.0
        return self.total_duration_ms / self.calls

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.calls == 0:
            return 0.0
        return (self.successes / self.calls) * 100


@dataclass
class AgentStats:
    """Comprehensive statistics for agent execution."""

    # Counters
    total_user_messages: int = 0
    total_assistant_messages: int = 0
    total_tool_calls: int = 0

    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Timing
    total_llm_duration_ms: float = 0.0
    total_tool_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    llm_call_count: int = 0

    # Tool-specific stats
    tool_stats: dict[str, ToolExecutionStats] = field(default_factory=dict)

    # Session metadata
    session_start: datetime = field(default_factory=datetime.now)
    session_end: datetime | None = None

    def record_llm_call(
        self,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        """Record an LLM API call.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            duration_ms: Duration of the call in milliseconds.
        """
        self.llm_call_count += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_llm_duration_ms += duration_ms

    def record_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Record a tool execution.

        Args:
            tool_name: Name of the tool that was called.
            duration_ms: Duration of the tool execution in milliseconds.
            success: Whether the tool executed successfully.
        """
        self.total_tool_calls += 1
        self.total_tool_duration_ms += duration_ms

        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolExecutionStats(name=tool_name)

        stats = self.tool_stats[tool_name]
        stats.calls += 1
        stats.total_duration_ms += duration_ms
        if success:
            stats.successes += 1
        else:
            stats.failures += 1

    def record_user_message(self) -> None:
        """Record a user message."""
        self.total_user_messages += 1

    def record_assistant_message(self) -> None:
        """Record an assistant message."""
        self.total_assistant_messages += 1

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def avg_llm_duration_ms(self) -> float:
        """Average LLM call duration in milliseconds."""
        if self.llm_call_count == 0:
            return 0.0
        return self.total_llm_duration_ms / self.llm_call_count

    @property
    def session_duration_ms(self) -> float:
        """Total session duration in milliseconds."""
        end = self.session_end or datetime.now()
        return (end - self.session_start).total_seconds() * 1000

    def print_summary(self) -> str:
        """Generate a human-readable summary of the statistics.

        Returns:
            Formatted string containing statistics summary.
        """
        lines = [
            "=== Agent Statistics Summary ===",
            "",
            "Messages:",
            f"  User: {self.total_user_messages}",
            f"  Assistant: {self.total_assistant_messages}",
            f"  Total: {self.total_user_messages + self.total_assistant_messages}",
            "",
            "Tokens:",
            f"  Input: {self.total_input_tokens:,}",
            f"  Output: {self.total_output_tokens:,}",
            f"  Total: {self.total_tokens:,}",
            "",
            "LLM Calls:",
            f"  Count: {self.llm_call_count}",
            f"  Avg Duration: {self.avg_llm_duration_ms:.2f}ms",
            f"  Total Duration: {self.total_llm_duration_ms:.2f}ms",
            "",
            "Tool Calls:",
            f"  Total: {self.total_tool_calls}",
            f"  Total Duration: {self.total_tool_duration_ms:.2f}ms",
        ]

        if self.tool_stats:
            lines.extend(["", "By Tool:"])
            for name, stats in sorted(
                self.tool_stats.items(),
                key=lambda x: x[1].calls,
                reverse=True,
            ):
                lines.append(
                    f"  {name}: {stats.calls} calls, "
                    f"{stats.success_rate:.1f}% success, "
                    f"{stats.avg_duration_ms:.2f}ms avg"
                )

        lines.extend(
            [
                "",
                "Session:",
                f"  Duration: {self.session_duration_ms / 1000:.2f}s",
                f"  Start: {self.session_start.isoformat()}",
            ]
        )

        if self.session_end:
            lines.append(f"  End: {self.session_end.isoformat()}")

        return "\n".join(lines)

