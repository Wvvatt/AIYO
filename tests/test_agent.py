"""Basic tests for the Agent class."""

from unittest.mock import MagicMock, patch

from any_llm.types.completion import ChatCompletion

from aiyo import Agent


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
    def _make_agent(self, tools=None):
        with patch("aiyo.agent.AnyLLM"):
            agent = Agent(tools=tools, system="test system")
        return agent

    def test_run_returns_reply(self):
        agent = self._make_agent()
        agent._llm.completion.return_value = make_mock_response("Hello, world!")
        assert agent.chat("Hi") == "Hello, world!"

    def test_history_accumulates_across_turns(self):
        agent = self._make_agent()
        agent._llm.completion.side_effect = [
            make_mock_response("First reply"),
            make_mock_response("Second reply"),
        ]
        agent.chat("Turn 1")
        agent.chat("Turn 2")
        roles = [m["role"] for m in agent._history]
        assert roles == ["system", "user", "assistant", "user", "assistant"]

    def test_reset_clears_history(self):
        agent = self._make_agent()
        agent._llm.completion.return_value = make_mock_response("Hi")
        agent.chat("Hello")
        agent.reset()
        assert agent._history == [{"role": "system", "content": "test system"}]

    def test_tool_is_called(self):
        called_with = {}

        def my_tool(name: str) -> str:
            """A test tool.

            Args:
                name: Input name.
            """
            called_with["name"] = name
            return f"Hi, {name}!"

        agent = self._make_agent(tools=[my_tool])

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "my_tool"
        tool_call.function.arguments = '{"name": "Alice"}'

        agent._llm.completion.side_effect = [
            make_mock_response("", tool_calls=[tool_call]),
            make_mock_response("Done!"),
        ]

        assert agent.chat("Do the thing") == "Done!"
        assert called_with["name"] == "Alice"

    def test_unknown_tool_returns_error(self):
        agent = self._make_agent()

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "nonexistent_tool"
        tool_call.function.arguments = "{}"

        agent._llm.completion.side_effect = [
            make_mock_response("", tool_calls=[tool_call]),
            make_mock_response("Handled error."),
        ]

        assert agent.chat("trigger unknown tool") == "Handled error."

    def test_max_iterations_guard(self):
        agent = self._make_agent()
        agent._max_iterations = 3

        tool_call = MagicMock()
        tool_call.id = "call_loop"
        tool_call.function.name = "nonexistent"
        tool_call.function.arguments = "{}"

        agent._llm.completion.return_value = make_mock_response("", tool_calls=[tool_call])
        assert "max" in agent.chat("loop forever").lower()
