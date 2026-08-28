import pytest
from app.connectors.base import (
    ConnectorAuthType,
    ConnectorCategory,
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
from app.integrations.secrets import InMemorySecretVault
from app.tools.registry import ToolRegistry
from app.mcp.server_config import MCPServerConfig
from app.mcp.client import MCPClient


class DummyTransport:
    async def request(self, method: str, params: dict | None = None) -> dict:
        if method == "initialize":
            return {"serverInfo": {"name": "dummy-mcp", "version": "1.0"}}
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "search_database",
                        "description": "Search customer records",
                        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                    },
                    {
                        "name": "delete_customer",
                        "description": "Delete a customer account",
                        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
                    },
                ]
            }
        elif method == "tools/call":
            return {"result": f"Executed {params.get('name')} with {params.get('arguments')}"}
        return {}

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_connector_registry_lifecycle():
    vault = InMemorySecretVault()
    tool_reg = ToolRegistry()
    registry = ConnectorRegistry(secret_vault=vault, tool_registry=tool_reg)

    github = GitHubConnector()
    registry.register_connector(github)

    # Initial state
    listed = registry.list_connectors()
    assert len(listed) >= 1
    gh_entry = next(c for c in listed if c["id"] == "github")
    assert gh_entry["status"] == "disconnected"
    assert len(gh_entry["tools"]) == 7

    # Connect with token
    res = await registry.connect("github", {"token": "ghp_test_token_123"})
    assert res["status"] == "connected"
    assert github.status == ConnectorStatus.CONNECTED

    # Verify tools synced to ToolRegistry
    tools = tool_reg.list()
    assert any(t.metadata.name == "github.list_repositories" for t in tools)
    assert any(t.metadata.name == "github.merge_pull_request" for t in tools)

    # Disconnect
    await registry.disconnect("github")
    assert github.status == ConnectorStatus.DISCONNECTED
    # Tools should be cleanly removed from ToolRegistry
    tools_after = tool_reg.list()
    assert not any(t.metadata.name.startswith("github.") for t in tools_after)


@pytest.mark.asyncio
async def test_github_connector_tools_execution():
    github = GitHubConnector()
    await github.connect({"token": "mock_token"})

    # Test list repositories
    repos = await github.execute_tool("list_repositories", {})
    assert len(repos) >= 1

    # Test search issues
    issues = await github.execute_tool("search_issues", {"query": "is:open"})
    assert len(issues) >= 1

    # Test create issue
    new_issue = await github.execute_tool("create_issue", {"repo": "owner/repo", "title": "Test Issue", "body": "Details"})
    assert new_issue["title"] == "Test Issue"
    assert new_issue["repo"] == "owner/repo"


@pytest.mark.asyncio
async def test_gmail_and_calendar_connectors():
    gmail = GmailConnector()
    await gmail.connect({"address": "user@gmail.com", "app_password": "abcd-efgh-ijkl-mnop"})
    emails = await gmail.execute_tool("search_emails", {"query": "is:unread"})
    assert len(emails) >= 1

    draft = await gmail.execute_tool("create_draft", {"to": "test@test.com", "subject": "Hi", "body": "Content"})
    assert draft["status"] == "draft_created"

    cal = CalendarConnector()
    await cal.connect({})
    events = await cal.execute_tool("search_events", {})
    assert len(events) >= 1

    avail = await cal.execute_tool("get_availability", {"date": "2026-08-28"})
    assert "free_slots" in avail


@pytest.mark.asyncio
async def test_plugin_sdk_define_connector():
    async def my_exec(tool_name: str, args: dict, ctx: any):
        if tool_name == "ping":
            return {"pong": True, "echo": args.get("msg")}
        raise NotImplementedError

    custom_plugin = define_connector(
        id="echo_plugin",
        name="Echo Plugin",
        description="Simple custom plugin for testing",
        category=ConnectorCategory.COMMUNICATION,
        tools=[
            {
                "name": "ping",
                "description": "Send a ping message",
                "input_schema": {"type": "object", "properties": {"msg": {"type": "string"}}},
                "risk_level": "low",
            }
        ],
        execute_fn=my_exec,
    )

    await custom_plugin.connect({})
    assert custom_plugin.status == ConnectorStatus.CONNECTED
    res = await custom_plugin.execute_tool("ping", {"msg": "hello vyom"})
    assert res["pong"] is True
    assert res["echo"] == "hello vyom"


@pytest.mark.asyncio
async def test_dynamic_mcp_connector_discovery():
    client = MCPClient(DummyTransport())
    config = MCPServerConfig(id="db_server", name="Database MCP", transport="stdio", command="node")
    mcp_adapter = MCPConnectorAdapter(config, client)

    res = await mcp_adapter.connect({})
    assert res["status"] == "connected"
    assert res["tool_count"] == 2

    # Check discovered tools and risk levels
    tools = mcp_adapter.list_tools()
    search_tool = next(t for t in tools if t.name == "search_database")
    delete_tool = next(t for t in tools if t.name == "delete_customer")

    assert search_tool.risk_level == RiskLevel.LOW
    assert delete_tool.risk_level == RiskLevel.HIGH
    assert delete_tool.requires_approval is True

    # Execute discovered tool
    exec_res = await mcp_adapter.execute_tool("search_database", {"query": "SELECT *"})
    assert "Executed search_database" in exec_res["result"]
