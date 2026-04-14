"""Basic tests for the Agent class."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from any_llm.types.completion import ChatCompletion

from aiyo.agent.agent import Agent


def make_mock_response(content: str, tool_calls=None):
    """Build a mock any-llm completion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = message
    response = MagicMock(spec=ChatCompletion)
    response.choices = [choice]
    return response


class TestAgent:
    @pytest.fixture
    def agent(self):
        """Create an agent with mocked LLM."""
        with patch("aiyo.agent.agent.AnyLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm_class.create.return_value = mock_llm
            agent = Agent(system="test system")
            yield agent

    @pytest.mark.asyncio
    async def test_run_returns_reply(self, agent):
        """Test that chat returns the LLM response."""
        agent._llm.acompletion = AsyncMock(return_value=make_mock_response("Hello, world!"))

        result = await agent.chat("Hi")

        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_history_accumulates_across_turns(self, agent):
        """Test that conversation history accumulates."""
        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("First reply"),
            make_mock_response("Second reply"),
        ])

        await agent.chat("Turn 1")
        await agent.chat("Turn 2")

        roles = [m["role"] for m in agent._history.get_history()]
        assert roles == ["system", "user", "assistant", "user", "assistant"]

    def test_reset_clears_history(self, agent):
        """Test that reset clears history."""
        agent._llm.acompletion = AsyncMock(return_value=make_mock_response("Hi"))
        
        asyncio.run(agent.chat("Hello"))
        agent.reset()

        history = agent._history.get_history()
        assert len(history) == 1
        assert history[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_tool_is_called(self, agent):
        """Test that tools are called when requested."""
        called_with = {}

        async def my_tool(name: str) -> str:
            """A test tool.

            Args:
                name: Input name.
            """
            called_with["name"] = name
            return f"Hi, {name}!"

        # Add custom tool to agent
        agent._tools.append(my_tool)
        agent._tool_map["my_tool"] = my_tool

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "my_tool"
        tool_call.function.arguments = '{"name": "Alice"}'

        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("", tool_calls=[tool_call]),
            make_mock_response("Done!"),
        ])

        result = await agent.chat("Do the thing")

        assert result == "Done!"
        assert called_with["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_readonly_tools_run_in_parallel(self, agent):
        """Read-only tools (names in _GATHER_TOOL_NAMES) execute concurrently."""
        from aiyo.agent.agent import _GATHER_TOOL_NAMES

        async def read_file(path: str) -> str:  # noqa: ARG001
            """Read a file."""
            await asyncio.sleep(0.2)
            return "content"

        async def glob_files(pattern: str) -> str:  # noqa: ARG001
            """Glob files."""
            await asyncio.sleep(0.2)
            return "matches"

        assert "read_file" in _GATHER_TOOL_NAMES
        assert "glob_files" in _GATHER_TOOL_NAMES

        agent._tool_map["read_file"] = read_file
        agent._tool_map["glob_files"] = glob_files

        tc1 = MagicMock()
        tc1.id = "call_1"
        tc1.function.name = "read_file"
        tc1.function.arguments = '{"path": "a.txt"}'

        tc2 = MagicMock()
        tc2.id = "call_2"
        tc2.function.name = "glob_files"
        tc2.function.arguments = '{"pattern": "*.py"}'

        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("", tool_calls=[tc1, tc2]),
            make_mock_response("Done!"),
        ])

        t0 = time.monotonic()
        result = await agent.chat("read and glob")
        elapsed = time.monotonic() - t0

        assert result == "Done!"
        assert elapsed < 0.35, f"Read-only tools should run concurrently, got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_mutation_tools_run_serially(self, agent):
        """Mutation tools (non-gatherable) execute one at a time."""
        order: list[str] = []

        async def tool_a() -> str:
            """Mutation tool A."""
            order.append("a_start")
            await asyncio.sleep(0.05)
            order.append("a_end")
            return "a"

        async def tool_b() -> str:
            """Mutation tool B."""
            order.append("b_start")
            await asyncio.sleep(0.05)
            order.append("b_end")
            return "b"

        agent._tools.extend([tool_a, tool_b])
        agent._tool_map["tool_a"] = tool_a
        agent._tool_map["tool_b"] = tool_b

        tc1 = MagicMock()
        tc1.id = "call_1"
        tc1.function.name = "tool_a"
        tc1.function.arguments = "{}"

        tc2 = MagicMock()
        tc2.id = "call_2"
        tc2.function.name = "tool_b"
        tc2.function.arguments = "{}"

        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("", tool_calls=[tc1, tc2]),
            make_mock_response("Done!"),
        ])

        result = await agent.chat("run both")

        assert result == "Done!"
        assert order == ["a_start", "a_end", "b_start", "b_end"], "Mutations must be serial"

    @pytest.mark.asyncio
    async def test_list_arg_string_is_coerced_by_middleware(self, agent):
        """Test weak-model string list args are normalized to list."""
        captured = {}

        async def list_tool(tags: list[str]) -> str:
            """A test tool that expects list input."""
            captured["tags"] = tags
            return "ok"

        agent._tools.append(list_tool)
        agent._tool_map["list_tool"] = list_tool

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "list_tool"
        tool_call.function.arguments = '{"tags": "a,b,c"}'

        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("", tool_calls=[tool_call]),
            make_mock_response("Done!"),
        ])

        result = await agent.chat("Do the thing")

        assert result == "Done!"
        assert captured["tags"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, agent):
        """Test that unknown tools are handled gracefully."""
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "nonexistent_tool"
        tool_call.function.arguments = "{}"

        agent._llm.acompletion = AsyncMock(side_effect=[
            make_mock_response("", tool_calls=[tool_call]),
            make_mock_response("Handled error."),
        ])

        result = await agent.chat("trigger unknown tool")

        assert result == "Handled error."

    def test_structured_tool_result_is_serialized_as_json(self, agent):
        """Test dict/list tool results are stored as JSON tool content."""
        tool_msg, user_msg = agent._result_to_messages("call_1", {"ok": True, "tasks": []})

        assert user_msg is None
        assert tool_msg is not None
        assert json.loads(tool_msg["content"]) == {"ok": True, "tasks": []}

    @pytest.mark.asyncio
    async def test_max_iterations_guard(self, agent):
        """Test that max iterations is enforced."""
        agent._max_iterations = 3

        tool_call = MagicMock()
        tool_call.id = "call_loop"
        tool_call.function.name = "nonexistent"
        tool_call.function.arguments = "{}"

        agent._llm.acompletion = AsyncMock(return_value=make_mock_response("", tool_calls=[tool_call]))

        result = await agent.chat("loop forever")

        assert "maximum" in result.lower() or "max" in result.lower()

    @pytest.mark.asyncio
    async def test_cancellation_propagated(self, agent):
        """Test that CancelledError is propagated, not wrapped."""
        agent._llm.acompletion = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await agent.chat("trigger cancellation")

    @pytest.mark.asyncio
    async def test_cancellation_during_tool_call(self, agent):
        """Test that CancelledError during tool execution is propagated."""
        async def slow_tool():
            """A slow tool that gets cancelled."""
            raise asyncio.CancelledError()

        agent._tools.append(slow_tool)
        agent._tool_map["slow_tool"] = slow_tool

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "slow_tool"
        tool_call.function.arguments = "{}"

        agent._llm.acompletion = AsyncMock(return_value=make_mock_response("", tool_calls=[tool_call]))

        with pytest.raises(asyncio.CancelledError):
            await agent.chat("trigger tool cancellation")

    @pytest.mark.asyncio
    async def test_cancellation_does_not_pollute_history(self, agent):
        """Test that cancellation during LLM call does not pollute conversation history."""
        # Simulate cancellation during LLM call
        agent._llm.acompletion = AsyncMock(side_effect=asyncio.CancelledError())

        history_before = len(agent._history.get_history())

        with pytest.raises(asyncio.CancelledError):
            await agent.chat("trigger cancellation")

        # History should only contain system + user message, no incomplete assistant message
        history_after = agent._history.get_history()
        assert len(history_after) == history_before + 1  # Only user message added
        assert history_after[-1]["role"] == "user"
