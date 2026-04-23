"""MCP client integration for AIYO agents."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiyo.config import settings
from aiyo.tools.tool_meta import tool

logger = logging.getLogger(__name__)

_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_MCP_MANAGER: McpToolManager | None = None


@dataclass(slots=True)
class McpServerConfig:
    """Configuration for one MCP server."""

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def load_mcp_config() -> list[McpServerConfig]:
    """Load MCP server config from env/default JSON files."""
    path = _find_config_path()
    if path is None:
        return []

    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning("Ignoring empty MCP config file: %s", path)
            return []
        raw = json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"Failed to read MCP config {path}: {exc}") from exc

    servers = raw.get("mcpServers", raw.get("servers", {}))
    if not isinstance(servers, dict):
        raise RuntimeError(f"MCP config {path} must contain an object named mcpServers")

    configs: list[McpServerConfig] = []
    for name, value in servers.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"MCP server '{name}' config must be an object")
        configs.append(
            McpServerConfig(
                name=str(name),
                transport=str(value.get("transport") or _infer_transport(value)),
                command=value.get("command"),
                args=[str(arg) for arg in value.get("args", [])],
                env={str(k): str(v) for k, v in value.get("env", {}).items()},
                cwd=value.get("cwd"),
                url=value.get("url"),
                headers={str(k): str(v) for k, v in value.get("headers", {}).items()},
            )
        )
    return configs


class McpToolManager:
    """Own MCP sessions and expose their tools as local async callables."""

    def __init__(self, configs: list[McpServerConfig] | None = None) -> None:
        self._configs = configs if configs is not None else load_mcp_config()
        self._config_by_name = {config.name: config for config in self._configs}
        self._tools: list[Any] = []
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._configs)

    async def ensure_initialized(self) -> list[Any]:
        """Initialize configured MCP sessions once and return wrapped tools."""
        if self._initialized:
            return self._tools

        async with self._lock:
            if self._initialized:
                return self._tools

            if not self._configs:
                self._initialized = True
                return self._tools

            try:
                from mcp import ClientSession
            except ImportError as exc:
                raise RuntimeError(
                    "MCP is configured but the Python package 'mcp' is not installed. "
                    "Install project dependencies after updating pyproject.toml."
                ) from exc

            for config in self._configs:
                async with self._open_session(config, ClientSession) as session:
                    listed = await session.list_tools()
                for remote_tool in listed.tools:
                    self._tools.append(self._wrap_tool(config.name, remote_tool))

            self._initialized = True
            logger.info("Loaded %d MCP tools from %d servers", len(self._tools), len(self._configs))
            return self._tools

    async def close(self) -> None:
        """Reset cached MCP tools."""
        self._tools.clear()
        self._initialized = False

    async def health(self, server_name: str) -> dict[str, Any]:
        """Check whether an MCP server can connect and initialize."""
        config = self._config_by_name.get(server_name)
        if config is None:
            return {
                "name": f"mcp:{server_name}",
                "status": "not_configured",
                "message": "server config missing",
            }

        try:
            try:
                from mcp import ClientSession
            except ImportError as exc:
                raise RuntimeError("Python package 'mcp' is not installed") from exc

            async with self._open_session(config, ClientSession):
                pass
            message = config.url or config.command or config.transport
            return {"name": f"mcp:{server_name}", "status": "ok", "message": message}
        except Exception as exc:
            return {"name": f"mcp:{server_name}", "status": "error", "message": str(exc)}

    @asynccontextmanager
    async def _open_session(
        self, config: McpServerConfig, client_session: Any
    ) -> AsyncGenerator[Any]:
        async with AsyncExitStack() as stack:
            yield await self._connect(config, client_session, stack)

    async def _connect(
        self, config: McpServerConfig, client_session: Any, stack: AsyncExitStack
    ) -> Any:
        transport = config.transport.lower().replace("-", "_")
        if transport == "stdio":
            if not config.command:
                raise RuntimeError(f"MCP server '{config.name}' requires command for stdio")
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params_kwargs: dict[str, Any] = {
                "command": config.command,
                "args": config.args,
                "env": config.env or None,
            }
            if config.cwd and "cwd" in inspect.signature(StdioServerParameters).parameters:
                params_kwargs["cwd"] = config.cwd
            params = StdioServerParameters(**params_kwargs)
            read, write = await stack.enter_async_context(stdio_client(params))
        elif transport in {"streamable_http", "streamableHttp", "http", "sse"}:
            if not config.url:
                raise RuntimeError(f"MCP server '{config.name}' requires url for HTTP transport")
            import httpx
            from mcp.client.streamable_http import streamable_http_client

            http_client = None
            if config.headers:
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(headers=config.headers)
                )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(config.url, http_client=http_client)
            )
        else:
            raise RuntimeError(f"Unsupported MCP transport '{config.transport}' for {config.name}")

        session = await stack.enter_async_context(client_session(read, write))
        await session.initialize()
        return session

    def _wrap_tool(self, server_name: str, remote_tool: Any) -> Any:
        remote_name = remote_tool.name
        local_name = _safe_tool_name(f"mcp__{server_name}__{remote_name}")
        description = remote_tool.description or f"MCP tool {remote_name} from {server_name}."
        schema = getattr(remote_tool, "inputSchema", None) or {}
        signature = _signature_from_schema(schema)

        def summary(args: dict[str, Any]) -> str:
            return f"{server_name}.{remote_name}({', '.join(args)})"

        async def health_check() -> dict[str, Any]:
            return await self.health(server_name)

        @tool(gatherable=False, summary=summary, health_check=health_check)
        async def mcp_tool(**kwargs: Any) -> Any:
            """Call a tool exposed by an MCP server."""
            config = self._config_by_name[server_name]
            try:
                from mcp import ClientSession
            except ImportError as exc:
                raise RuntimeError("Python package 'mcp' is not installed") from exc

            async with self._open_session(config, ClientSession) as session:
                result = await session.call_tool(remote_name, arguments=kwargs)
            return _serialize_call_result(result)

        mcp_tool.__name__ = local_name
        mcp_tool.__qualname__ = local_name
        mcp_tool.__doc__ = description
        mcp_tool.__signature__ = signature
        mcp_tool.__annotations__ = {
            name: parameter.annotation
            for name, parameter in signature.parameters.items()
            if parameter.annotation is not inspect.Parameter.empty
        }
        mcp_tool.__annotations__["return"] = Any
        return mcp_tool


def get_mcp_manager() -> McpToolManager:
    """Return the process-wide MCP tool manager."""
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        _MCP_MANAGER = McpToolManager()
    return _MCP_MANAGER


async def close_mcp_manager() -> None:
    """Close and reset the process-wide MCP tool manager."""
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        return
    await _MCP_MANAGER.close()
    _MCP_MANAGER = None


def _find_config_path() -> Path | None:
    if settings.mcp_config:
        return settings.mcp_config.expanduser()

    for path in (
        settings.work_dir / ".aiyo" / "mcp.json",
        Path.home() / ".aiyo" / "mcp.json",
    ):
        if path.is_file():
            return path
    return None


def _infer_transport(value: dict[str, Any]) -> str:
    if value.get("url"):
        return "streamable_http"
    return "stdio"


def _safe_tool_name(name: str) -> str:
    cleaned = _TOOL_NAME_RE.sub("_", name).strip("_")
    return cleaned[:64] or "mcp_tool"


def _signature_from_schema(schema: dict[str, Any]) -> inspect.Signature:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    parameters: list[inspect.Parameter] = []

    if not isinstance(properties, dict):
        properties = {}

    for name, prop_schema in properties.items():
        if not isinstance(name, str) or not name.isidentifier():
            continue
        annotation = _annotation_from_schema(prop_schema if isinstance(prop_schema, dict) else {})
        default = inspect.Parameter.empty if name in required else None
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    return inspect.Signature(parameters=parameters, return_annotation=Any)


def _annotation_from_schema(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "string")

    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list
    if schema_type == "object":
        return dict
    return str


def _serialize_call_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        prefix = "Error: MCP tool failed"
    else:
        prefix = ""

    content = getattr(result, "content", None)
    if content is None:
        return result

    parts: list[Any] = []
    for item in content:
        item_type = getattr(item, "type", None)
        if item_type == "text":
            parts.append(getattr(item, "text", ""))
        else:
            parts.append(_model_dump(item))

    if len(parts) == 1 and isinstance(parts[0], str):
        return f"{prefix}: {parts[0]}" if prefix else parts[0]
    if prefix:
        return {"error": prefix, "content": parts}
    return parts


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)
