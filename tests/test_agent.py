"""Basic tests for the Agent class."""

import asyncio
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
