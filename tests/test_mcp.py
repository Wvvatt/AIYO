"""Tests for MCP integration."""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any

import pytest

from aiyo.config import settings
from aiyo.mcp import (
    McpServerConfig,
    McpToolManager,
    close_mcp_manager,
    get_mcp_manager,
    load_mcp_config,
)
from aiyo.tools import health_check


def test_load_mcp_config_from_file(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "demo": {
              "command": "python",
              "args": ["server.py"],
              "env": {"TOKEN": "abc"}
            },
            "remote": {
              "url": "http://localhost:8000/mcp",
              "headers": {"Authorization": "Bearer token"}
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "mcp_config", config_path)

    configs = load_mcp_config()

    assert configs[0] == McpServerConfig(
        name="demo",
        transport="stdio",
        command="python",
        args=["server.py"],
        env={"TOKEN": "abc"},
    )
    assert configs[1].name == "remote"
    assert configs[1].transport == "streamable_http"
    assert configs[1].url == "http://localhost:8000/mcp"


@pytest.mark.asyncio
async def test_mcp_manager_no_config_has_no_tools():
    manager = McpToolManager([])

    tools = await manager.ensure_initialized()

    assert tools == []


@pytest.mark.asyncio
async def test_get_mcp_manager_returns_process_singleton():
    await close_mcp_manager()
    try:
        assert get_mcp_manager() is get_mcp_manager()
    finally:
        await close_mcp_manager()


@pytest.mark.asyncio
async def test_mcp_manager_wraps_and_calls_remote_tool(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", SimpleNamespace(ClientSession=object))

    class FakeSession:
        async def list_tools(self) -> Any:
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="echo",
                        description="Echo text.",
                        inputSchema={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    )
                ]
            )

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            assert name == "echo"
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text=arguments["text"])],
            )

    async def fake_connect(
        config: McpServerConfig, client_session: Any, stack: AsyncExitStack
    ) -> Any:
        assert stack
        assert config.name == "demo"
        assert client_session is object
        return FakeSession()

    manager = McpToolManager([McpServerConfig(name="demo", command="server")])
    monkeypatch.setattr(manager, "_connect", fake_connect)

    tools = await manager.ensure_initialized()

    assert len(tools) == 1
    assert tools[0].__name__ == "mcp__demo__echo"
    assert await tools[0](text="hello") == "hello"
    assert await health_check(tools[0]) == {
        "name": "mcp:demo",
        "status": "ok",
        "message": "server",
    }
