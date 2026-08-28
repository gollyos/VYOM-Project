from __future__ import annotations

import json
import logging
from typing import Any
from app.connectors.base import BaseConnector, ConnectorDefinition, ConnectorStatus, ToolDefinition
from app.integrations.secrets import SecretVault, WindowsDPAPISecretVault, InMemorySecretVault

logger = logging.getLogger("vyom.connectors.registry")


class ConnectorRegistry:
    """Central registry and lifecycle manager for all Vyom Connectors, Plugins, and MCP bridges."""

    def __init__(self, secret_vault: SecretVault | None = None, tool_registry: Any = None):
        self.secret_vault = secret_vault or InMemorySecretVault()
        self.tool_registry = tool_registry
        self._connectors: dict[str, BaseConnector] = {}
        self._catalog: dict[str, ConnectorDefinition] = {}

    def register_catalog_entry(self, definition: ConnectorDefinition, connector_instance: BaseConnector | None = None) -> None:
        """Register an available connector in the catalog."""
        self._catalog[definition.id] = definition
        if connector_instance:
            self._connectors[definition.id] = connector_instance

    def register_connector(self, connector: BaseConnector) -> None:
        """Register an active or configurable connector instance."""
        self._connectors[connector.definition.id] = connector
        self._catalog[connector.definition.id] = connector.definition
        if connector.status == ConnectorStatus.CONNECTED and self.tool_registry:
            self._sync_tools_to_registry(connector)

    def get_connector(self, connector_id: str) -> BaseConnector | None:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[dict[str, Any]]:
        """Return full list of connectors with status, capability, and tools."""
        result = []
        for cid, defn in self._catalog.items():
            conn = self._connectors.get(cid)
            status = conn.status.value if conn else ConnectorStatus.DISCONNECTED.value
            tools_list = [t.model_dump(mode="json") for t in (conn.list_tools() if conn else defn.tools)]
            result.append({
                **defn.model_dump(mode="json"),
                "status": status,
                "installed": conn is not None and conn.status == ConnectorStatus.CONNECTED,
                "error": conn.error_message if conn else None,
                "tools": tools_list,
            })
        return result

    async def connect(self, connector_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        """Authenticate and connect a connector."""
        connector = self._connectors.get(connector_id)
        if not connector:
            raise KeyError(f"Connector '{connector_id}' not found")

        # Save credentials in secure encrypted vault
        cred_key = f"connector:{connector_id}"
        self.secret_vault.set(cred_key, json.dumps(credentials).encode("utf-8"))

        try:
            result = await connector.connect(credentials)
            connector.status = ConnectorStatus.CONNECTED
            connector.error_message = None
            if self.tool_registry:
                self._sync_tools_to_registry(connector)
            return {"status": "connected", "result": result}
        except Exception as e:
            connector.status = ConnectorStatus.ERROR
            connector.error_message = str(e)
            logger.error("Failed to connect %s: %s", connector_id, str(e))
            raise

    async def disconnect(self, connector_id: str) -> dict[str, Any]:
        """Disconnect and revoke connector credentials."""
        connector = self._connectors.get(connector_id)
        if not connector:
            raise KeyError(f"Connector '{connector_id}' not found")

        try:
            await connector.disconnect()
        except Exception as e:
            logger.warning("Error during disconnect of %s: %s", connector_id, str(e))

        connector.status = ConnectorStatus.DISCONNECTED
        connector.error_message = None

        # Remove from vault
        cred_key = f"connector:{connector_id}"
        self.secret_vault.delete(cred_key)

        # Unregister tools from ToolRegistry
        if self.tool_registry:
            self.tool_registry.unregister_prefix(f"{connector_id}.")

        return {"status": "disconnected"}

    def _sync_tools_to_registry(self, connector: BaseConnector) -> None:
        """Register connector tools into Vyom's shared ToolRegistry."""
        from app.tools.base import BaseTool, ToolMetadata
        from app.tools.context import ToolContext
        from app.tools.result import ToolResult, EvidenceItem
        from app.schemas.approvals import PermissionLevel

        class ConnectorToolAdapter(BaseTool):
            def __init__(self, conn: BaseConnector, tdef: ToolDefinition):
                self.conn = conn
                self.tdef = tdef
                perm = PermissionLevel.L3 if tdef.risk_level.value == "high" else (
                    PermissionLevel.L2 if tdef.risk_level.value == "medium" else PermissionLevel.L0
                )
                self.metadata = ToolMetadata(
                    name=tdef.id,
                    description=tdef.description,
                    category=tdef.category,
                    required_permissions=[perm],
                    input_schema=tdef.input_schema,
                    output_schema=tdef.output_schema,
                    risk_level=tdef.risk_level.value,
                )

            async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
                output = await self.conn.execute_tool(self.tdef.name, inputs, context)
                evidence = EvidenceItem(
                    type="tool_result",
                    summary=f"Connector {self.conn.definition.id} tool {self.tdef.name} executed",
                    data={"connector": self.conn.definition.id, "tool": self.tdef.name, "output": output},
                )
                return ToolResult.completed(evidence.summary, output=output, evidence=[evidence])

        for tdef in connector.list_tools():
            adapter = ConnectorToolAdapter(connector, tdef)
            self.tool_registry.register(adapter)
