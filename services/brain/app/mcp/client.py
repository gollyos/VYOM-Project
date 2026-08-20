from __future__ import annotations

from typing import Any, Protocol


class MCPTransport(Protocol):
    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class MCPClient:
    def __init__(self, transport: MCPTransport):
        self.transport = transport
        self.connected = False

    async def connect(self) -> dict[str, Any]:
        result = await self.transport.request(
            "initialize",
            {"protocolVersion": "2025-06-18", "clientInfo": {"name": "vyom", "version": "0.1.0"}, "capabilities": {}},
        )
        self.connected = True
        return result

    async def disconnect(self) -> None:
        await self.transport.close()
        self.connected = False

    async def list_tools(self) -> list[dict[str, Any]]:
        return list((await self.transport.request("tools/list")).get("tools", []))

    async def list_resources(self) -> list[dict[str, Any]]:
        return list((await self.transport.request("resources/list")).get("resources", []))

    async def invoke_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.transport.request("tools/call", {"name": name, "arguments": arguments})

    async def health(self) -> dict[str, Any]:
        return {"healthy": self.connected, "status": "connected" if self.connected else "disconnected"}
