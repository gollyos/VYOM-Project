from __future__ import annotations

from typing import Any
import logging
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)
from app.mcp.client import MCPClient
from app.mcp.server_config import MCPServerConfig

logger = logging.getLogger("vyom.connectors.mcp")


class MCPConnectorAdapter(BaseConnector):
    """Bridges any MCP (Model Context Protocol) Server into the universal Connector Framework."""

    def __init__(self, server_config: MCPServerConfig, client: MCPClient | None = None):
        defn = ConnectorDefinition(
            id=f"mcp_{server_config.id}",
            name=server_config.name or f"MCP: {server_config.id}",
            slug=f"mcp-{server_config.id}",
            description=f"Model Context Protocol integration for {server_config.id} ({server_config.transport} transport).",
            icon="server",
            category=ConnectorCategory.CUSTOM_MCP,
            auth_type=ConnectorAuthType.MCP,
            capabilities=["mcp_tools", "mcp_resources", "dynamic_discovery"],
            metadata={
                "server_id": server_config.id,
                "transport": server_config.transport,
                "command": server_config.command,
                "args": server_config.args,
            },
        )
        super().__init__(defn)
        self.server_config = server_config
        self.client = client

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError(f"MCP client not initialized for {self.server_config.id}")
        
        init_result = await self.client.connect()
        # Dynamically discover exposed MCP tools
        raw_tools = await self.client.list_tools()
        
        discovered_tools: list[ToolDefinition] = []
        for r_tool in raw_tools:
            name = str(r_tool.get("name", ""))
            desc = str(r_tool.get("description", ""))
            schema = dict(r_tool.get("inputSchema", {}))
            
            # Smart risk classification
            risk = RiskLevel.LOW
            lower_name = name.lower()
            if any(k in lower_name for k in ["delete", "remove", "drop", "terminate", "send", "publish", "merge", "pay", "order"]):
                risk = RiskLevel.HIGH
            elif any(k in lower_name for k in ["create", "update", "write", "post", "edit", "modify", "draft"]):
                risk = RiskLevel.MEDIUM

            discovered_tools.append(
                ToolDefinition(
                    id=f"{self.definition.id}.{name}",
                    connector_id=self.definition.id,
                    name=name,
                    display_name=name.replace("_", " ").title(),
                    description=desc,
                    category="mcp",
                    input_schema=schema,
                    risk_level=risk,
                    requires_approval=risk == RiskLevel.HIGH,
                )
            )

        self.definition.tools = discovered_tools
        self._tools = {t.name: t for t in discovered_tools}
        self.status = ConnectorStatus.CONNECTED
        return {
            "status": "connected",
            "server_id": self.server_config.id,
            "tool_count": len(discovered_tools),
            "tools": [t.name for t in discovered_tools],
        }

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
        self.status = ConnectorStatus.DISCONNECTED
        self._tools.clear()

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)
        if not self.client or not self.client.connected:
            raise RuntimeError(f"MCP server '{self.server_config.id}' is not connected")
        return await self.client.invoke_tool(tool_name, arguments)
