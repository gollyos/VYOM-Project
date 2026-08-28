from __future__ import annotations

from typing import Any, Callable, Coroutine
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)


class FunctionalConnector(BaseConnector):
    """Dynamic connector built via the define_connector SDK helper."""

    def __init__(
        self,
        definition: ConnectorDefinition,
        connect_handler: Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]] | None = None,
        disconnect_handler: Callable[[], Coroutine[Any, Any, None]] | None = None,
        execute_handler: Callable[[str, dict[str, Any], Any], Coroutine[Any, Any, Any]] | None = None,
        status_handler: Callable[[], Coroutine[Any, Any, dict[str, Any]]] | None = None,
    ):
        super().__init__(definition)
        self._connect_handler = connect_handler
        self._disconnect_handler = disconnect_handler
        self._execute_handler = execute_handler
        self._status_handler = status_handler

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        if self._connect_handler:
            result = await self._connect_handler(credentials)
            self.status = ConnectorStatus.CONNECTED
            return result
        self.status = ConnectorStatus.CONNECTED
        return {"status": "connected"}

    async def disconnect(self) -> None:
        if self._disconnect_handler:
            await self._disconnect_handler()
        self.status = ConnectorStatus.DISCONNECTED

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)
        if self._execute_handler:
            return await self._execute_handler(tool_name, arguments, context)
        raise NotImplementedError(f"No execution handler registered for tool {tool_name}")

    async def status_check(self) -> dict[str, Any]:
        if self._status_handler:
            return await self._status_handler()
        return await super().status_check()


def define_connector(
    *,
    id: str,
    name: str,
    slug: str | None = None,
    description: str,
    icon: str = "plug",
    category: ConnectorCategory = ConnectorCategory.CUSTOM_REST,
    auth_type: ConnectorAuthType = ConnectorAuthType.API_KEY,
    capabilities: list[str] | None = None,
    permissions: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    connect_fn: Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]] | None = None,
    disconnect_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
    execute_fn: Callable[[str, dict[str, Any], Any], Coroutine[Any, Any, Any]] | None = None,
    status_fn: Callable[[], Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> BaseConnector:
    """Helper for declaring custom Vyom plugins & connectors concisely."""
    tool_defs: list[ToolDefinition] = []
    for t in tools or []:
        risk = RiskLevel(t.get("risk_level", "low").lower())
        tool_defs.append(
            ToolDefinition(
                id=f"{id}.{t['name']}",
                connector_id=id,
                name=t["name"],
                display_name=t.get("display_name", t["name"].replace("_", " ").title()),
                description=t.get("description", ""),
                category=t.get("category", category.value),
                input_schema=t.get("input_schema", {}),
                output_schema=t.get("output_schema", {}),
                permissions=t.get("permissions", []),
                risk_level=risk,
                requires_approval=t.get("requires_approval", risk == RiskLevel.HIGH),
                timeout_seconds=float(t.get("timeout_seconds", 30.0)),
                retry_policy=t.get("retry_policy", {"max_retries": 2, "backoff": 1.5}),
                metadata=t.get("metadata", {}),
            )
        )

    definition = ConnectorDefinition(
        id=id,
        name=name,
        slug=slug or id.lower().replace("_", "-"),
        description=description,
        icon=icon,
        category=category,
        auth_type=auth_type,
        capabilities=capabilities or [],
        permissions=permissions or [],
        tools=tool_defs,
    )

    return FunctionalConnector(
        definition=definition,
        connect_handler=connect_fn,
        disconnect_handler=disconnect_fn,
        execute_handler=execute_fn,
        status_handler=status_fn,
    )
