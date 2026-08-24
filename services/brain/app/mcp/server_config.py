from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.config import expand_environment
from app.schemas.approvals import PermissionLevel

from .adapter import MCPToolAdapter
from .client import MCPClient
from .registry import MCPRegistry, MCPServer
from .stdio_transport import MCPStdioError, StdioTransport


class MCPServerConfig(BaseModel):
    """One entry from config/tools.yaml: mcp_servers. This is how VYOM
    is told which external MCP servers exist and how to reach them — it
    never invents a server or a command on its own. Adding a server here
    (or through POST /api/mcp/servers) is the explicit, auditable act of
    granting VYOM a new capability; VYOM then handles discovery, tool
    registration, health, and reconnection itself."""

    id: str
    name: str = ""
    enabled: bool = True
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    trust_level: str = "restricted"
    tool_permission: PermissionLevel = PermissionLevel.L2
    timeout_seconds: float = 30.0


def load_mcp_server_configs(path: Path) -> list[MCPServerConfig]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    raw = expand_environment(raw)
    entries = raw.get("mcp_servers") or []
    return [MCPServerConfig.model_validate(entry) for entry in entries]


class MCPConnectionManager:
    """Owns the lifecycle of every configured/added MCP server: connect,
    register its real tools into the shared ToolRegistry so the rest of
    VYOM (planner, agents, skills) can call them like any other tool,
    disconnect, and reconnect. A server that fails to start or times out
    is recorded as unhealthy and never blocks boot or another server —
    the whole point of auto-connect is that it degrades gracefully."""

    def __init__(self, registry: MCPRegistry, tool_registry, project_root: Path):
        self.registry = registry
        self.tool_registry = tool_registry
        self.project_root = project_root
        self._configs: dict[str, MCPServerConfig] = {}

    def _build_transport(self, config: MCPServerConfig):
        if config.transport != "stdio":
            raise MCPStdioError(f"Unsupported MCP transport '{config.transport}' for server '{config.id}'")
        if not config.command:
            raise MCPStdioError(f"MCP server '{config.id}' has no command configured")
        return StdioTransport(
            command=config.command,
            args=config.args,
            env=config.env,
            cwd=config.cwd or str(self.project_root),
            timeout_seconds=config.timeout_seconds,
        )

    async def connect(self, config: MCPServerConfig) -> dict[str, Any]:
        """Connect one server, discover its tools, and register adapters
        for each. Returns a status dict; never raises — a broken server
        config is reported, not fatal."""
        self._configs[config.id] = config
        transport = self._build_transport(config)
        client = MCPClient(transport)
        server = MCPServer(
            server_id=config.id,
            name=config.name or config.id,
            transport="stdio-local",
            status="connecting",
            trust_level=config.trust_level,
        )
        self.registry.register(server, client)
        try:
            await client.connect()
            tools = await client.list_tools()
            for definition in tools:
                adapter = MCPToolAdapter(
                    server_id=config.id,
                    definition=definition,
                    client=client,
                    permission=config.tool_permission,
                )
                self.tool_registry.register(adapter)
            server.status = "connected"
            server.tools = list(tools)
            server.capabilities = ["tools"]
            return {"server_id": config.id, "status": "connected", "tool_count": len(tools),
                     "tools": [tool.get("name") for tool in tools]}
        except Exception as error:
            server.status = "error"
            await client.disconnect()
            return {"server_id": config.id, "status": "error", "detail": str(error)[:300]}

    async def connect_all(self, configs: list[MCPServerConfig]) -> list[dict[str, Any]]:
        results = []
        for config in configs:
            if not config.enabled:
                continue
            results.append(await self.connect(config))
        return results

    async def disconnect(self, server_id: str) -> bool:
        client = self.registry.clients.get(server_id)
        if client is None:
            return False
        await client.disconnect()
        self.tool_registry.unregister_prefix(f"mcp.{server_id}.")
        self.registry.servers.pop(server_id, None)
        self.registry.clients.pop(server_id, None)
        return True

    async def reconnect(self, server_id: str) -> dict[str, Any]:
        config = self._configs.get(server_id)
        if config is None:
            return {"server_id": server_id, "status": "error", "detail": "no known configuration for this server"}
        await self.disconnect(server_id)
        return await self.connect(config)
