from __future__ import annotations

from typing import Any

from .client import MCPClient


class MCPDiscovery:
    async def inspect(self, client: MCPClient) -> dict[str, Any]:
        return {
            "tools": await client.list_tools(),
            "resources": await client.list_resources(),
            "health": await client.health(),
        }
