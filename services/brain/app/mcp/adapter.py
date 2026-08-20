from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.result import EvidenceItem, ToolResult

from .client import MCPClient


class MCPToolAdapter(BaseTool):
    def __init__(
        self,
        *,
        server_id: str,
        definition: dict[str, Any],
        client: MCPClient,
        permission: PermissionLevel = PermissionLevel.L2,
    ):
        self.server_id = server_id
        self.remote_name = str(definition["name"])
        self.client = client
        self.metadata = ToolMetadata(
            name=f"mcp.{server_id}.{self.remote_name}",
            description=str(definition.get("description", "Restricted MCP tool")),
            category="mcp",
            required_permissions=[permission],
            input_schema=dict(definition.get("inputSchema", {})),
            output_schema={},
            risk_level="medium" if permission != PermissionLevel.L3 else "high",
        )

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        response = await self.client.invoke_tool(self.remote_name, inputs)
        evidence = EvidenceItem(
            type="tool_result",
            summary=f"MCP tool {self.remote_name} invoked",
            data={"server_id": self.server_id, "tool": self.remote_name, "response": response},
        )
        await context.emit("mcp_tool_invoked", evidence.summary, evidence.data)
        return ToolResult.completed(evidence.summary, output=response, evidence=[evidence])
