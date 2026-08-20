from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .client import MCPClient


class MCPServer(BaseModel):
    server_id: str
    name: str
    transport: str
    status: str = "disconnected"
    capabilities: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    last_health_check: str | None = None
    trust_level: str = "restricted"


class MCPRegistry:
    def __init__(self):
        self.servers: dict[str, MCPServer] = {}
        self.clients: dict[str, MCPClient] = {}

    def register(self, server: MCPServer, client: MCPClient) -> None:
        if server.trust_level not in {"restricted", "trusted"}:
            raise ValueError("MCP trust level must be restricted or trusted")
        self.servers[server.server_id] = server
        self.clients[server.server_id] = client

    async def refresh(self, server_id: str) -> MCPServer:
        server, client = self.servers[server_id], self.clients[server_id]
        health = await client.health()
        server.status = "connected" if health["healthy"] else "disconnected"
        server.last_health_check = datetime.now(timezone.utc).isoformat()
        if health["healthy"]:
            server.tools = await client.list_tools()
            server.capabilities = ["tools"]
        return server

    def describe(self) -> list[dict[str, Any]]:
        return [server.model_dump(mode="json") for server in self.servers.values()]
