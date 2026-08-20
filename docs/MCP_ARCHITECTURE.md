# VYOM MCP Architecture

MCP is a tool source beneath VYOM's execution boundary, not a separate authority.

## Components

- `MCPClient` normalizes initialize, tool/resource listing, invocation, health, and disconnect over a transport.
- `MCPDiscovery` inspects advertised tools/resources without granting execution permission.
- `MCPRegistry` stores server identity, transport, status, capabilities, tools, last health check, and trust level.
- `MCPToolAdapter` converts one remote schema into the universal VYOM Tool Protocol.

## Trust and permissions

New servers default to `restricted`. Discovery never changes trust. Every adapted MCP tool has an explicit VYOM permission requirement and is invoked only through `ToolExecutor`, so it receives event logging, cancellation, evidence, and task budget boundaries.

An MCP server cannot lower its own risk, approve itself, access secrets from frontend state, or bypass path/command/browser policies. High-impact remote tools remain L2/L3 even when a server advertises them as safe.

## Current scope

Phase 5 implements the client contract, registry, discovery, health model, and adapter with mocked protocol tests. No server is auto-discovered or configured by default. Concrete stdio/HTTP transports and user-approved server onboarding remain configuration work, not implicit network scanning.

## Phase 13.5

The external codebase-memory-mcp server integrates through this
existing registry at restricted trust (`app/mcp/codebase_memory.py`),
limited to registered project roots, with automatic filesystem/search
fallback when unavailable. The server is user-run; VYOM never installs
external MCP servers automatically.
