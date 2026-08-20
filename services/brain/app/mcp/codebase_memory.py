from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .client import MCPClient
from .registry import MCPRegistry, MCPServer


class CodebaseMemoryTransport:
    """Transport contract for the external codebase-memory-mcp server
    (DeusData/codebase-memory-mcp). The real server is NOT installed in
    this environment — production points `request` at a locally running
    server process the USER started; tests inject a controlled fake.
    VYOM never clones or installs it automatically."""

    async def request(self, method: str, payload: dict) -> dict:
        raise NotImplementedError("no codebase-memory-mcp server is configured")

    async def close(self) -> None:
        return None


class CodebaseMemoryHealth:
    """Lightweight health: no AI calls, no reindexing — one ping."""

    @staticmethod
    async def check(client: MCPClient) -> dict:
        try:
            health = await client.health()
        except Exception as error:
            return {"healthy": False, "detail": str(error)[:120]}
        return health


@dataclass
class StructuralAnswer:
    answer: str
    backend: str          # codebase-memory | filesystem-fallback
    evidence: list[str]


class CodebaseMemoryAdapter:
    """Structural code understanding through the EXISTING MCP Registry
    (restricted trust by default). Routing is context-dependent:

      "where is this function used"  -> codebase-memory (symbol refs)
      "read the exact implementation" -> filesystem read
      "search exact text"            -> grep/search tool
      "run tests"                    -> terminal

    If the MCP is unavailable/unhealthy/indexing, coding falls back to
    the existing filesystem/search tools — it never stops. Indexing is
    limited to REGISTERED project roots through the existing Path
    Policy; the server never receives unrestricted filesystem scope."""

    SERVER_ID = "codebase-memory"

    def __init__(self, registry: MCPRegistry, allowed_roots: list[Path]):
        self.registry = registry
        self.allowed_roots = [Path(root).resolve() for root in allowed_roots]

    def register(self, transport: CodebaseMemoryTransport, *, trusted: bool = False) -> MCPServer:
        server = MCPServer(
            server_id=self.SERVER_ID,
            name="codebase-memory (external)",
            transport="stdio-local",
            status="disconnected",
            capabilities=["code.structure", "code.references"],
            trust_level="trusted" if trusted else "restricted",
        )
        self.registry.register(server, MCPClient(transport))
        return server

    def _path_allowed(self, root: str | Path) -> bool:
        try:
            resolved = Path(root).resolve()
        except Exception:
            return False
        return any(resolved == allowed or allowed in resolved.parents for allowed in self.allowed_roots)

    async def ask_structural(self, question: str, project_root: str | Path) -> StructuralAnswer:
        if not self._path_allowed(project_root):
            return StructuralAnswer(
                answer=f"Project root {project_root} is not registered; structural memory is limited to registered roots.",
                backend="filesystem-fallback",
                evidence=["path policy restriction"],
            )
        server = self.registry.servers.get(self.SERVER_ID)
        if server is None or server.status != "connected":
            fallback = await self.filesystem_fallback(question, project_root)
            fallback.evidence.insert(0, "codebase-memory unavailable")
            return fallback
        client = self.registry.clients[self.SERVER_ID]
        try:
            result = await client.invoke_tool("query_structure", {
                "question": question, "root": str(project_root),
            })
        except Exception as error:
            fallback = await self.filesystem_fallback(question, project_root)
            fallback.evidence.insert(0, f"codebase-memory error: {str(error)[:80]}")
            return fallback
        return StructuralAnswer(
            answer=str(result.get("answer", "")), backend="codebase-memory",
            evidence=list(result.get("evidence", []))[:10],
        )

    async def filesystem_fallback(self, question: str, project_root: str | Path) -> StructuralAnswer:
        """Deterministic structural fallback using stdlib scanning of
        REGISTERED roots only — a stand-in for the existing grep/read
        tools so coding questions never hard-fail."""
        root = Path(project_root).resolve()
        keywords = [word for word in question.lower().split() if len(word) > 3][:4]
        hits: list[str] = []
        if root.exists():
            for path in sorted(root.rglob("*.py"))[:400]:
                if any(part in {"node_modules", ".git", "__pycache__", "target"} for part in path.parts):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if not keywords or any(keyword in text.lower() for keyword in keywords):
                    hits.append(str(path.relative_to(root)))
                if len(hits) >= 10:
                    break
        summary = (f"codebase-memory unavailable; filesystem scan of {root.name} found "
                   f"{len(hits)} file(s) matching the structural question.")
        return StructuralAnswer(answer=summary, backend="filesystem-fallback", evidence=hits)
