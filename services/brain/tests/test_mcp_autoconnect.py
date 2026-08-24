"""Tests for real MCP auto-connect: stdio transport, config loading, and
the connection manager that wires discovered tools into the shared
ToolRegistry. These exercise the NEW subsystem added so VYOM can connect
to real MCP servers itself instead of only ever offering a Protocol
nobody implemented.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.mcp.client import MCPClient
from app.mcp.registry import MCPRegistry
from app.mcp.server_config import MCPConnectionManager, MCPServerConfig, load_mcp_server_configs
from app.mcp.stdio_transport import MCPStdioError, StdioTransport
from app.schemas.approvals import PermissionLevel
from app.tools.registry import ToolRegistry


# A tiny in-process fake "server" driven over a pair of pipes would need a
# real subprocess to exercise StdioTransport honestly (it owns a real
# asyncio.subprocess.Process). We spawn `python -c <script>` as the
# server — this is exactly the same code path a real MCP server takes
# (some other interpreter/binary instead of `python -c`).
_FAKE_SERVER_SCRIPT = r"""
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "fixture"}, "capabilities": {}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "echo", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        args = (req.get("params") or {}).get("arguments") or {}
        result = {"content": [{"type": "text", "text": args.get("text", "")}]}
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown"}}) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
    sys.stdout.flush()
"""


def _fixture_transport(**kwargs) -> StdioTransport:
    import sys

    return StdioTransport(command=sys.executable, args=["-c", _FAKE_SERVER_SCRIPT], **kwargs)


@pytest.mark.asyncio
async def test_stdio_transport_completes_a_real_request_response_cycle():
    """The transport spawns a REAL child process and speaks real
    newline-delimited JSON-RPC to it — not a mock."""
    transport = _fixture_transport(timeout_seconds=10)
    client = MCPClient(transport)
    try:
        init = await client.connect()
        assert init["serverInfo"]["name"] == "fixture"
        tools = await client.list_tools()
        assert [tool["name"] for tool in tools] == ["echo"]
        result = await client.invoke_tool("echo", {"text": "hello"})
        assert result["content"][0]["text"] == "hello"
        assert (await client.health())["healthy"] is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_stdio_transport_reports_missing_command_honestly():
    transport = StdioTransport(command="vyom-nonexistent-command-xyz", timeout_seconds=5)
    with pytest.raises(MCPStdioError, match="not found"):
        await transport.request("initialize")


@pytest.mark.asyncio
async def test_stdio_transport_times_out_instead_of_hanging_forever():
    """A server that never answers must not block a task forever - this
    is what makes auto-connect safe to run unattended."""
    import sys

    # `python -c "import time; time.sleep(30)"` never writes a response.
    transport = StdioTransport(
        command=sys.executable, args=["-c", "import time; time.sleep(30)"], timeout_seconds=1,
    )
    with pytest.raises(MCPStdioError, match="did not respond"):
        await transport.request("initialize")
    await transport.close()


@pytest.mark.asyncio
async def test_stdio_transport_survives_a_response_larger_than_the_default_asyncio_buffer():
    """Regression: asyncio's default StreamReader limit is 64KB and a
    real MCP server (e.g. a directory listing) can legitimately answer
    with one JSON line far larger than that."""
    import sys

    big_text = "x" * 200_000  # far past the 64KB default asyncio limit
    script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        f"    payload = 'x' * 200000\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {'echo': payload}}) + chr(10))\n"
        "    sys.stdout.flush()\n"
    )
    transport = StdioTransport(command=sys.executable, args=["-c", script], timeout_seconds=10)
    try:
        result = await transport.request("anything")
        assert len(result["echo"]) == 200_000
    finally:
        await transport.close()


def test_load_mcp_server_configs_returns_empty_for_missing_file(tmp_path: Path):
    assert load_mcp_server_configs(tmp_path / "does-not-exist.yaml") == []


def test_load_mcp_server_configs_parses_real_yaml(tmp_path: Path):
    config_path = tmp_path / "tools.yaml"
    config_path.write_text(
        "mcp_servers:\n"
        "  - id: demo\n"
        "    name: Demo Server\n"
        "    command: npx\n"
        "    args: [\"-y\", \"some-server\"]\n"
        "    trust_level: restricted\n",
        encoding="utf-8",
    )
    configs = load_mcp_server_configs(config_path)
    assert len(configs) == 1
    assert configs[0].id == "demo"
    assert configs[0].command == "npx"
    assert configs[0].args == ["-y", "some-server"]


@pytest.mark.asyncio
async def test_connection_manager_registers_discovered_tools_into_the_shared_registry(monkeypatch, tmp_path: Path):
    """This is the actual auto-connect contract: connecting a server must
    make its tools callable through the SAME ToolRegistry every built-in
    tool uses - not a separate, second-class registry the planner never
    sees."""
    registry = MCPRegistry()
    tool_registry = ToolRegistry()
    manager = MCPConnectionManager(registry, tool_registry, tmp_path)

    import sys

    monkeypatch.setattr(
        manager, "_build_transport",
        lambda config: StdioTransport(command=sys.executable, args=["-c", _FAKE_SERVER_SCRIPT], timeout_seconds=10),
    )
    config = MCPServerConfig(id="demo", command="unused-because-monkeypatched")
    outcome = await manager.connect(config)

    assert outcome["status"] == "connected"
    assert outcome["tool_count"] == 1
    registered = tool_registry.get("mcp.demo.echo")
    assert registered.metadata.name == "mcp.demo.echo"
    assert registry.servers["demo"].status == "connected"


@pytest.mark.asyncio
async def test_connection_manager_disconnect_removes_tools_from_the_registry(monkeypatch, tmp_path: Path):
    registry = MCPRegistry()
    tool_registry = ToolRegistry()
    manager = MCPConnectionManager(registry, tool_registry, tmp_path)

    import sys

    monkeypatch.setattr(
        manager, "_build_transport",
        lambda config: StdioTransport(command=sys.executable, args=["-c", _FAKE_SERVER_SCRIPT], timeout_seconds=10),
    )
    config = MCPServerConfig(id="demo", command="unused")
    await manager.connect(config)
    assert tool_registry.get("mcp.demo.echo") is not None

    removed = await manager.disconnect("demo")
    assert removed is True
    with pytest.raises(Exception):
        tool_registry.get("mcp.demo.echo")
    assert "demo" not in registry.servers


@pytest.mark.asyncio
async def test_connection_manager_reports_a_broken_server_without_raising(tmp_path: Path):
    """A misconfigured server must degrade to a reported error, never
    crash the caller - this is what makes `connect_all` safe at boot."""
    registry = MCPRegistry()
    tool_registry = ToolRegistry()
    manager = MCPConnectionManager(registry, tool_registry, tmp_path)

    config = MCPServerConfig(id="broken", command="vyom-nonexistent-command-xyz", timeout_seconds=2)
    outcome = await manager.connect(config)
    assert outcome["status"] == "error"
    assert registry.servers["broken"].status == "error"


@pytest.mark.asyncio
async def test_connect_all_skips_disabled_servers(monkeypatch, tmp_path: Path):
    registry = MCPRegistry()
    tool_registry = ToolRegistry()
    manager = MCPConnectionManager(registry, tool_registry, tmp_path)

    import sys

    monkeypatch.setattr(
        manager, "_build_transport",
        lambda config: StdioTransport(command=sys.executable, args=["-c", _FAKE_SERVER_SCRIPT], timeout_seconds=10),
    )
    configs = [
        MCPServerConfig(id="on", command="unused", enabled=True),
        MCPServerConfig(id="off", command="unused", enabled=False),
    ]
    results = await manager.connect_all(configs)
    assert len(results) == 1
    assert results[0]["server_id"] == "on"
    assert "off" not in registry.servers
