from __future__ import annotations

from typing import Any
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)


class GmailConnector(BaseConnector):
    """Gmail integration connector for reading, searching, drafting, and sending emails."""

    def __init__(self, email_address: str | None = None, app_password: str | None = None):
        defn = ConnectorDefinition(
            id="gmail",
            name="Gmail",
            slug="gmail",
            description="Read, search, summarize emails, compose contextual drafts, and send outgoing messages.",
            icon="mail",
            category=ConnectorCategory.COMMUNICATION,
            auth_type=ConnectorAuthType.OAUTH2,
            capabilities=["search", "threads", "drafts", "send"],
            permissions=["gmail.readonly", "gmail.compose", "gmail.send"],
            tools=[
                ToolDefinition(
                    id="gmail.search_emails",
                    connector_id="gmail",
                    name="search_emails",
                    display_name="Search Emails",
                    description="Search your Gmail inbox and archives using search terms (e.g. 'is:unread', 'from:client@example.com').",
                    category="communication",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query syntax"},
                            "max_results": {"type": "integer", "default": 5},
                        },
                        "required": ["query"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="gmail.read_thread",
                    connector_id="gmail",
                    name="read_thread",
                    display_name="Read Email Thread",
                    description="Retrieve full content and messages for a specific email thread.",
                    category="communication",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "thread_id": {"type": "string", "description": "Gmail Thread ID"},
                        },
                        "required": ["thread_id"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="gmail.create_draft",
                    connector_id="gmail",
                    name="create_draft",
                    display_name="Create Draft Email",
                    description="Create a draft email in your Gmail account without sending it.",
                    category="communication",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Subject line"},
                            "body": {"type": "string", "description": "Email body content"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="gmail.send_email",
                    connector_id="gmail",
                    name="send_email",
                    display_name="Send Outgoing Email",
                    description="Send an email to external recipients. (High Risk - Requires Approval)",
                    category="communication",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Subject line"},
                            "body": {"type": "string", "description": "Email body content"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                    risk_level=RiskLevel.HIGH,
                    requires_approval=True,
                ),
            ],
        )
        super().__init__(defn)
        self.email_address = email_address
        self.app_password = app_password

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        self.email_address = credentials.get("address") or credentials.get("email")
        self.app_password = credentials.get("app_password") or credentials.get("token")
        if not self.email_address:
            raise ValueError("Email address is required")
        self.status = ConnectorStatus.CONNECTED
        return {"status": "connected", "email": self.email_address}

    async def disconnect(self) -> None:
        self.email_address = None
        self.app_password = None
        self.status = ConnectorStatus.DISCONNECTED

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)
        if tool_name == "search_emails":
            return [
                {
                    "id": "msg_001",
                    "thread_id": "th_1001",
                    "from": "sarah@techcorp.io",
                    "subject": "Project update and weekly sync",
                    "snippet": "Hi team, here is the recap for the Sprint 42 deliverable...",
                    "date": "2026-08-28T09:30:00Z",
                },
                {
                    "id": "msg_002",
                    "thread_id": "th_1002",
                    "from": "alerts@monitoring.cloud",
                    "subject": "System Health Status: All Green",
                    "snippet": "All edge services and cluster nodes operating nominally.",
                    "date": "2026-08-28T08:00:00Z",
                },
            ]
        elif tool_name == "read_thread":
            return {
                "thread_id": arguments["thread_id"],
                "subject": "Project update and weekly sync",
                "messages": [
                    {
                        "from": "sarah@techcorp.io",
                        "to": "me@vyom.ai",
                        "body": "Hi team, here is the recap for the Sprint 42 deliverable. All core features look solid. Please review the checklist.",
                        "date": "2026-08-28T09:30:00Z",
                    }
                ],
            }
        elif tool_name == "create_draft":
            return {
                "draft_id": "draft_999",
                "to": arguments["to"],
                "subject": arguments["subject"],
                "body": arguments["body"],
                "status": "draft_created",
            }
        elif tool_name == "send_email":
            return {
                "message_id": "msg_sent_888",
                "to": arguments["to"],
                "subject": arguments["subject"],
                "status": "sent",
            }
        raise NotImplementedError(f"Tool {tool_name} not implemented on Gmail connector")
