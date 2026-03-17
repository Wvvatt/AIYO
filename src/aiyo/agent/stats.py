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
class SessionStats:
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

    def format_report(self) -> str:
        """Generate a human-readable statistics report as plain-text tables.

        Returns:
            Formatted string containing statistics summary.
        """

        def _row(label: str, value: str, w: int = 14) -> str:
            return f"  {label:<{w}}  {value}"

        def _hline(width: int = 40) -> str:
            return "  " + "-" * width

        lines: list[str] = ["Session Stats", ""]
        # ── Overview ──────────────────────────────────────────────────────
        lines.append(
            _row(
                "Messages",
                f"{self.total_user_messages} user / {self.total_assistant_messages} assistant",
            )
        )
        lines.append(
            _row(
                "Tokens",
                f"{self.total_input_tokens:,} in / {self.total_output_tokens:,} out  ({self.total_tokens:,} total)",
            )
        )
        lines.append(
            _row(
                "LLM calls",
                f"{self.llm_call_count}  avg {self.avg_llm_duration_ms:.0f} ms  total {self.total_llm_duration_ms / 1000:.1f} s",
            )
        )
        lines.append(
            _row(
                "Tool calls",
                f"{self.total_tool_calls}  total {self.total_tool_duration_ms / 1000:.1f} s",
            )
        )
        lines.append(_row("Duration", f"{self.session_duration_ms / 1000:.1f} s"))

        # ── Per-tool table ─────────────────────────────────────────────────
        if self.tool_stats:
            sorted_tools = sorted(self.tool_stats.items(), key=lambda x: x[1].calls, reverse=True)
            name_w = max(len(n) for n, _ in sorted_tools)
            name_w = max(name_w, 4)

            lines.append("")
            header = f"  {'Tool':<{name_w}}  {'Calls':>5}  {'Success':>7}  {'Avg ms':>6}"
            lines.append(header)
            lines.append("  " + "-" * (name_w + 24))
            for name, ts in sorted_tools:
                lines.append(
                    f"  {name:<{name_w}}  {ts.calls:>5}  {ts.success_rate:>6.0f}%  {ts.avg_duration_ms:>6.0f}"
                )

        return "\n".join(lines)
