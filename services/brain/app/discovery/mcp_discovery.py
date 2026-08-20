from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class MCPCandidate(BaseModel):
    name: str
    source: str
    capabilities: list[str] = Field(default_factory=list)
    publisher: str = "unknown"
    trust: str = "restricted"
    required_permissions: list[str] = Field(default_factory=list)
    installation_method: str = "manual configuration"
    risks: list[str] = Field(default_factory=list)
    already_connected: bool = False


DEFAULT_CATALOG: dict[str, dict[str, Any]] = {
    "filesystem-mcp": {
        "source": "local-catalog",
        "capabilities": ["filesystem.read", "filesystem.write"],
        "publisher": "community",
        "installation_method": "run as a local stdio server",
        "risks": ["broad filesystem access if misconfigured"],
    },
    "github-mcp": {
        "source": "local-catalog",
        "capabilities": ["repo.read", "issue.manage", "pull_request.manage"],
        "publisher": "community",
        "installation_method": "run as a local server with a personal access token",
        "risks": ["requires a personal access token with repo scope"],
    },
    "search-mcp": {
        "source": "local-catalog",
        "capabilities": ["web.search"],
        "publisher": "community",
        "installation_method": "run as an HTTP MCP server with a search API key",
        "risks": ["depends on a third-party search API key"],
    },
}


class MCPCatalog:
    """A small, explicitly curated catalog of publicly known MCP servers.
    VYOM does not scan the network to discover MCP servers."""

    def __init__(self, entries: dict[str, dict[str, Any]] | None = None):
        self.entries = entries if entries is not None else dict(DEFAULT_CATALOG)

    def search(self, capability_hint: str) -> list[tuple[str, dict[str, Any]]]:
        hint_tokens = set(re.findall(r"[a-z0-9]+", capability_hint.lower()))
        matches: list[tuple[str, dict[str, Any]]] = []
        for name, entry in self.entries.items():
            haystack_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
            for capability in entry.get("capabilities", []):
                haystack_tokens |= set(re.findall(r"[a-z0-9]+", capability.lower()))
            if hint_tokens & haystack_tokens:
                matches.append((name, entry))
        return matches


class MCPDiscoveryEngine:
    """New MCP servers are never auto-installed or auto-trusted. Every
    candidate must pass approval/security review before connection, and
    trust always starts restricted (see docs/MCP_ARCHITECTURE.md)."""

    def __init__(self, catalog: MCPCatalog, registry: Any = None):
        self.catalog = catalog
        self.registry = registry

    def discover(self, capability_hint: str) -> list[MCPCandidate]:
        connected_names: set[str] = set()
        if self.registry is not None and hasattr(self.registry, "servers"):
            connected_names = set(self.registry.servers.keys())
        candidates = []
        for name, entry in self.catalog.search(capability_hint):
            candidates.append(MCPCandidate(
                name=name,
                source=entry.get("source", "local-catalog"),
                capabilities=list(entry.get("capabilities", [])),
                publisher=entry.get("publisher", "unknown"),
                trust="restricted",
                installation_method=entry.get("installation_method", "manual configuration"),
                risks=list(entry.get("risks", [])),
                already_connected=name in connected_names,
            ))
        return candidates
