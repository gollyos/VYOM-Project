from __future__ import annotations

from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)
from app.connectors.registry import ConnectorRegistry
from app.connectors.plugin_sdk import define_connector
from app.connectors.builtin.github_connector import GitHubConnector
from app.connectors.builtin.gmail_connector import GmailConnector
from app.connectors.builtin.calendar_connector import CalendarConnector
from app.connectors.builtin.rest_connector import CustomRestConnector
from app.connectors.builtin.mcp_connector import MCPConnectorAdapter

__all__ = [
    "BaseConnector",
    "ConnectorAuthType",
    "ConnectorCategory",
    "ConnectorDefinition",
    "ConnectorStatus",
    "RiskLevel",
    "ToolDefinition",
    "ConnectorRegistry",
    "define_connector",
    "GitHubConnector",
    "GmailConnector",
    "CalendarConnector",
    "CustomRestConnector",
    "MCPConnectorAdapter",
]
