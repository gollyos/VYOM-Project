from __future__ import annotations

from pydantic import BaseModel


class MCPCatalogEntry(BaseModel):
    """A well-known, pre-vetted MCP server VYOM can offer by NAME instead
    of requiring the exact npx/uvx command line. This is a curated
    allowlist, not live discovery from the npm/PyPI registries — VYOM
    does not execute an arbitrary package just because a task mentioned
    it. Adding a catalog entry is a deliberate, reviewable code change;
    connecting one at runtime is the explicit POST /api/mcp/servers/from-catalog
    call (or an approved automation), never a silent side effect of a
    conversation."""

    catalog_id: str
    display_name: str
    description: str
    command: str
    args_template: list[str]
    #: True when a path argument must be filled in by the caller (e.g. the
    #: filesystem server needs a root directory it is allowed to touch).
    requires_path_arg: bool = False
    trust_level: str = "restricted"
    homepage: str = ""


#: Curated, hand-reviewed. Each entry has been proven to speak real MCP
#: (see tests/test_mcp_autoconnect.py and the filesystem server, which was
#: manually verified end-to-end: 14 real tools, real tool_call round trip).
CATALOG: list[MCPCatalogEntry] = [
    MCPCatalogEntry(
        catalog_id="filesystem",
        display_name="Filesystem",
        description="Read/write/search files under one or more directories you name.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-filesystem", "{path}"],
        requires_path_arg=True,
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    ),
    MCPCatalogEntry(
        catalog_id="memory",
        display_name="Knowledge Graph Memory",
        description="A persistent, queryable entity/relation memory graph.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-memory"],
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
    ),
    MCPCatalogEntry(
        catalog_id="fetch",
        display_name="Web Fetch",
        description="Fetch and convert a URL's content to markdown/text for reading.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-fetch"],
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
    ),
    MCPCatalogEntry(
        catalog_id="sequential-thinking",
        display_name="Sequential Thinking",
        description="A structured multi-step reasoning scratchpad tool.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
    ),
]


def find(catalog_id: str) -> MCPCatalogEntry | None:
    for entry in CATALOG:
        if entry.catalog_id == catalog_id:
            return entry
    return None


def describe() -> list[dict]:
    return [entry.model_dump(mode="json") for entry in CATALOG]
