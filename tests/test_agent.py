"""Basic tests for the Agent class."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from any_llm.types.completion import ChatCompletion

from aiyo.agent.agent import Agent
from aiyo.tools import tool


def make_mock_response(content: str, tool_calls=None, reasoning: str | None = None, finish_reason=None):
    """Build a mock any-llm completion response."""
    serialized_tool_calls = None
    if tool_calls:
        serialized_tool_calls = [
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

    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    message.reasoning = MagicMock(content=reasoning) if reasoning is not None else None
    message.model_dump.return_value = {
        "role": "assistant",
        "content": content,
        **({"tool_calls": serialized_tool_calls} if serialized_tool_calls else {}),
        **({"reasoning": {"content": reasoning}} if reasoning is not None else {}),
    }
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    response = MagicMock(spec=ChatCompletion)
    response.choices = [choice]
    return response


class TestAgent:
    @pytest.fixture
    def agent(self, tmp_path, monkeypatch):
        """Create an agent with mocked LLM."""
        mcp_config = tmp_path / "mcp.json"
        mcp_config.write_text("", encoding="utf-8")
        monkeypatch.setattr("aiyo.config.settings.mcp_config", mcp_config)
        with patch("aiyo.agent.agent.AnyLLM") as mock_llm_class:
            with patch("aiyo.agent.misc.AnyLLM") as mock_misc_llm_class:
                mock_llm = MagicMock()
                mock_llm_class.create.return_value = mock_llm

                # VisionMiddleware probes image support through aiyo.agent.misc.AnyLLM;
                # keep that probe mocked so timing tests only measure agent behavior.
                mock_vision_llm = MagicMock()
                mock_vision_llm.acompletion = AsyncMock(return_value=MagicMock())
                mock_misc_llm_class.create.return_value = mock_vision_llm

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

    @pytest.mark.asyncio
    async def test_assistant_reasoning_is_preserved_across_turns(self, agent):
        """Previous assistant reasoning must be replayed on the next user turn."""
        captured_calls = []

        async def fake_completion(**kwargs):
            captured_calls.append(kwargs["messages"])
            if len(captured_calls) == 1:
                return make_mock_response("First reply", reasoning="internal chain")
            return make_mock_response("Second reply")

        agent._llm.acompletion = AsyncMock(side_effect=fake_completion)

        await agent.chat("Turn 1")
        await agent.chat("Turn 2")

        second_call_messages = captured_calls[1]
        assistant_messages = [m for m in second_call_messages if m["role"] == "assistant"]
        assert assistant_messages
        assert assistant_messages[-1]["reasoning"] == {"content": "internal chain"}

    @pytest.mark.asyncio
    async def test_assistant_reasoning_is_preserved_during_tool_loop(self, agent):
        """Assistant reasoning must survive replay between tool iterations."""
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "nonexistent_tool"
        tool_call.function.arguments = "{}"

        captured_calls = []

        async def fake_completion(**kwargs):
            captured_calls.append(kwargs["messages"])
            if len(captured_calls) == 1:
                return make_mock_response(
                    "",
                    tool_calls=[tool_call],
                    reasoning="need to inspect files first",
                )
            return make_mock_response("Handled.")

        agent._llm.acompletion = AsyncMock(side_effect=fake_completion)

        result = await agent.chat("trigger tool")

        assert result == "Handled."
        second_call_messages = captured_calls[1]
        assistant_messages = [m for m in second_call_messages if m["role"] == "assistant"]
        assert assistant_messages
        assert assistant_messages[-1]["reasoning"] == {"content": "need to inspect files first"}

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
        """Read-only tools marked as gatherable execute concurrently."""
        @tool(gatherable=True)
        async def read_file(path: str) -> str:  # noqa: ARG001
            """Read a file."""
            await asyncio.sleep(0.2)
            return "content"

        @tool(gatherable=True)
        async def glob_files(pattern: str) -> str:  # noqa: ARG001
            """Glob files."""
            await asyncio.sleep(0.2)
            return "matches"

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
