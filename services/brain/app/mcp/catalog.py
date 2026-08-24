from __future__ import annotations

from pydantic import BaseModel, Field


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
    #: Environment variable NAMES this server needs (e.g. an API token) —
    #: never the values. The caller supplies real values via `env` on
    #: POST /api/mcp/servers/from-catalog; VYOM never invents, guesses, or
    #: stores a credential on the user's behalf. An entry with entries
    #: here is unusable until the caller provides them.
    required_env: list[str] = Field(default_factory=list)
    trust_level: str = "restricted"
    homepage: str = ""


#: Curated, hand-reviewed. Each npx-based entry has been proven to speak
#: real MCP for the categories exercised in tests/test_mcp_autoconnect.py
#: (the filesystem server was manually verified end-to-end: 14 real tools,
#: real tool_call round trip) — the credentialed entries below follow the
#: SAME @modelcontextprotocol/* or well-known community package shape but
#: require the user's own API token to actually connect, so they are listed
#: here as the reviewed, safe-to-offer set rather than live-verified.
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
    MCPCatalogEntry(
        catalog_id="notion",
        display_name="Notion",
        description="Read/search/create/update Notion pages and databases.",
        command="npx",
        args_template=["-y", "@notionhq/notion-mcp-server"],
        required_env=["NOTION_TOKEN"],
        homepage="https://github.com/makenotion/notion-mcp-server",
    ),
    MCPCatalogEntry(
        catalog_id="slack",
        display_name="Slack",
        description="Read channels, post messages, and search Slack workspace history.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-slack"],
        required_env=["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        homepage="https://github.com/modelcontextprotocol/servers-archived/tree/main/src/slack",
    ),
    MCPCatalogEntry(
        catalog_id="github",
        display_name="GitHub",
        description="Repos, issues, PRs, and code search over the GitHub API.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-github"],
        required_env=["GITHUB_PERSONAL_ACCESS_TOKEN"],
        homepage="https://github.com/modelcontextprotocol/servers-archived/tree/main/src/github",
    ),
    MCPCatalogEntry(
        catalog_id="postgres",
        display_name="PostgreSQL",
        description="Read-only inspection and querying of a Postgres database.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-postgres", "{connection_string}"],
        requires_path_arg=True,
        homepage="https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres",
    ),
    MCPCatalogEntry(
        catalog_id="brave-search",
        display_name="Brave Search",
        description="Web and local search via the Brave Search API.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-brave-search"],
        required_env=["BRAVE_API_KEY"],
        homepage="https://github.com/modelcontextprotocol/servers-archived/tree/main/src/brave-search",
    ),
    MCPCatalogEntry(
        catalog_id="puppeteer",
        display_name="Puppeteer Browser",
        description="An alternate headless-browser automation surface (screenshot, navigate, click, fill).",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-puppeteer"],
        homepage="https://github.com/modelcontextprotocol/servers-archived/tree/main/src/puppeteer",
    ),
]


def find(catalog_id: str) -> MCPCatalogEntry | None:
    for entry in CATALOG:
        if entry.catalog_id == catalog_id:
            return entry
    return None


def describe() -> list[dict]:
    return [entry.model_dump(mode="json") for entry in CATALOG]
