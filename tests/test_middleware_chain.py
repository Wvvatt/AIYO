from __future__ import annotations

import pytest
from aiyo.agent.middleware import (
    LLMResponseContext,
    Middleware,
    MiddlewareChain,
    ToolCallEndContext,
)


class _AppendMiddleware(Middleware):
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.seen_tool_error: object | None = None

    async def on_tool_call_end(self, ctx: ToolCallEndContext) -> None:
        self.seen_tool_error = ctx.tool_error
        ctx.result = f"{ctx.result}{self.suffix}"


@pytest.mark.asyncio
async def test_on_tool_call_end_chains_result_without_mutating_tool_error() -> None:
    chain = MiddlewareChain()
    m1 = _AppendMiddleware("-a")
    m2 = _AppendMiddleware("-b")
    chain.add(m1).add(m2)

    ctx = ToolCallEndContext(
        tool_name="tool",
        tool_id="id-1",
        tool_args={},
        tool_error=None,
        result="ok",
    )
    out = await chain.execute_hook("on_tool_call_end", ctx)

    assert out is ctx
    assert ctx.result == "ok-a-b"
    assert m1.seen_tool_error is None
    assert m2.seen_tool_error is None


@pytest.mark.asyncio
async def test_on_llm_response_still_chains_last_arg() -> None:
    class _LLMMiddleware(Middleware):
        def __init__(self, marker: str) -> None:
            self.marker = marker

        async def on_llm_response(self, ctx: LLMResponseContext) -> None:
            ctx.response = f"{ctx.response}{self.marker}"

    chain = MiddlewareChain()
    chain.add(_LLMMiddleware("-x")).add(_LLMMiddleware("-y"))
    ctx = LLMResponseContext(messages=[{"role": "user", "content": "hi"}], response="resp")
    await chain.execute_hook("on_llm_response", ctx)
    assert ctx.response == "resp-x-y"
