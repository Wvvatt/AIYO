from __future__ import annotations

import pytest

from aiyo.agent.middleware import Middleware, MiddlewareChain


class _AppendMiddleware(Middleware):
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.seen_tool_error: object | None = None

    async def on_tool_call_end(
        self,
        tool_name: str,
        tool_id: str,
        tool_args: dict[str, object],
        tool_error: Exception | None,
        result: object,
    ) -> object:
        self.seen_tool_error = tool_error
        return f"{result}{self.suffix}"


@pytest.mark.asyncio
async def test_on_tool_call_end_chains_result_without_mutating_tool_error() -> None:
    chain = MiddlewareChain()
    m1 = _AppendMiddleware("-a")
    m2 = _AppendMiddleware("-b")
    chain.add(m1).add(m2)

    out = await chain.execute_hook(
        "on_tool_call_end",
        "tool",
        "id-1",
        {},
        None,
        "ok",
    )

    assert out == "ok-a-b"
    assert m1.seen_tool_error is None
    assert m2.seen_tool_error is None


@pytest.mark.asyncio
async def test_on_llm_response_still_chains_last_arg() -> None:
    class _LLMMiddleware(Middleware):
        def __init__(self, marker: str) -> None:
            self.marker = marker

        async def on_llm_response(self, messages, response):  # type: ignore[override]
            return f"{response}{self.marker}"

    chain = MiddlewareChain()
    chain.add(_LLMMiddleware("-x")).add(_LLMMiddleware("-y"))
    out = await chain.execute_hook("on_llm_response", [{"role": "user", "content": "hi"}], "resp")
    assert out == "resp-x-y"
