from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable
from pydantic import BaseModel, Field


class ConnectorAuthType(str, Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    MCP = "mcp"
    INTERNAL = "internal"
    WEBHOOK = "webhook"
    NONE = "none"


class ConnectorCategory(str, Enum):
    COMMUNICATION = "communication"
    DEV_TOOLS = "dev_tools"
    PRODUCTIVITY = "productivity"
    STORAGE = "storage"
    CRM = "crm"
    ANALYTICS = "analytics"
    DATABASES = "databases"
    MARKETING = "marketing"
    AI = "ai"
    CUSTOM_MCP = "custom_mcp"
    CUSTOM_REST = "custom_rest"


class ConnectorStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    DISABLED = "disabled"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolDefinition(BaseModel):
    id: str
    connector_id: str
    name: str
    display_name: str = ""
    description: str = ""
    category: str = "general"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    timeout_seconds: float = 30.0
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max_retries": 2, "backoff": 1.5})
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorDefinition(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    icon: str = "plug"
    category: ConnectorCategory
    auth_type: ConnectorAuthType
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    tools: list[ToolDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class for all Vyom Connectors, Plugins, and MCP integrations."""

    def __init__(self, definition: ConnectorDefinition, config: dict[str, Any] | None = None):
        self.definition = definition
        self.config: dict[str, Any] = config or {}
        self.status = ConnectorStatus.DISCONNECTED
        self.error_message: str | None = None
        self._tools: dict[str, ToolDefinition] = {t.name: t for t in definition.tools}

    @abstractmethod
    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Establish connection with the service/provider."""
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly terminate connection and revoke/clear active session."""
        raise NotImplementedError

    async def refresh_auth(self) -> bool:
        """Refresh expired tokens if supported by auth_type."""
        return True

    def list_tools(self) -> list[ToolDefinition]:
        """Return list of exposed tools in normalized Vyom ToolDefinition format."""
        return list(self._tools.values())

    def get_tool(self, tool_name: str) -> ToolDefinition | None:
        """Fetch a specific tool definition by name."""
        return self._tools.get(tool_name)

    @abstractmethod
    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        """Execute a tool action exposed by this connector."""
        raise NotImplementedError

    async def status_check(self) -> dict[str, Any]:
        """Health check probe."""
        return {
            "id": self.definition.id,
            "status": self.status.value,
            "healthy": self.status == ConnectorStatus.CONNECTED,
            "error": self.error_message,
        }

    def validate_input(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Basic schema validation for required fields."""
        tool = self.get_tool(tool_name)
        if not tool:
            return False
        required_props = tool.input_schema.get("required", [])
        for req in required_props:
            if req not in arguments:
                raise ValueError(f"Missing required parameter '{req}' for tool '{tool_name}'")
        return True
