from __future__ import annotations

from typing import Any
import httpx
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)


class CustomRestConnector(BaseConnector):
    """Generic REST API Connector allowing users to connect any HTTP API dynamically."""

    def __init__(self, id: str, name: str, base_url: str, headers: dict[str, str] | None = None, tools: list[ToolDefinition] | None = None):
        defn = ConnectorDefinition(
            id=id,
            name=name,
            slug=id.lower().replace("_", "-"),
            description=f"Custom REST API integration for endpoint {base_url}",
            icon="globe",
            category=ConnectorCategory.CUSTOM_REST,
            auth_type=ConnectorAuthType.API_KEY,
            capabilities=["http_get", "http_post", "custom_endpoints"],
            tools=tools or [
                ToolDefinition(
                    id=f"{id}.http_request",
                    connector_id=id,
                    name="http_request",
                    display_name="Execute HTTP Request",
                    description=f"Send custom HTTP request to {base_url}",
                    category="custom_rest",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "default": "GET"},
                            "endpoint": {"type": "string", "description": "Relative URL path, e.g. /users"},
                            "params": {"type": "object", "description": "Query parameters"},
                            "body": {"type": "object", "description": "JSON request body for POST/PUT"},
                        },
                        "required": ["endpoint"],
                    },
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                )
            ],
            metadata={"base_url": base_url},
        )
        super().__init__(defn)
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.api_key: str | None = None

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        self.api_key = credentials.get("api_key") or credentials.get("token")
        auth_header = credentials.get("auth_header", "Authorization")
        auth_prefix = credentials.get("auth_prefix", "Bearer ")
        if self.api_key:
            self.headers[auth_header] = f"{auth_prefix}{self.api_key}" if auth_prefix else self.api_key
        self.status = ConnectorStatus.CONNECTED
        return {"status": "connected", "base_url": self.base_url}

    async def disconnect(self) -> None:
        self.api_key = None
        self.status = ConnectorStatus.DISCONNECTED

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)
        method = arguments.get("method", "GET").upper()
        endpoint = arguments["endpoint"].lstrip("/")
        url = f"{self.base_url}/{endpoint}"
        params = arguments.get("params")
        body = arguments.get("body")

        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.request(method=method, url=url, headers=self.headers, params=params, json=body)
            try:
                return res.json()
            except Exception:
                return {"status_code": res.status_code, "text": res.text}
