from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.memory.schemas import MemoryQuery, MemoryType
from app.memory.manager import MemoryManager


class CognitiveNamespace(str, Enum):
    """Logical cognitive domains for persistent intelligence. All
    intelligence stays in the structured stores — never thousands of
    loose .md/.txt files."""

    CODING = "coding"
    RESEARCH = "research"
    AGENCY = "agency"
    WEB = "web"
    MEDIA = "media"
    FINANCE = "finance"
    PERSONAL = "personal"
    PEOPLE = "people"
    PROJECTS = "projects"
    SYSTEM = "system"
    PREFERENCES = "preferences"


# Deterministic routing signals: task domain -> namespace, plus keyword
# overrides for content that domains alone misroute.
DOMAIN_NAMESPACES = {
    "coding": CognitiveNamespace.CODING,
    "research": CognitiveNamespace.RESEARCH,
    "agency": CognitiveNamespace.AGENCY,
    "general": CognitiveNamespace.SYSTEM,
    "communication": CognitiveNamespace.AGENCY,
    "analysis": CognitiveNamespace.RESEARCH,
    "creative": CognitiveNamespace.MEDIA,
    "finance": CognitiveNamespace.FINANCE,
    "personal": CognitiveNamespace.PERSONAL,
    "system": CognitiveNamespace.SYSTEM,
    "planning": CognitiveNamespace.PROJECTS,
}

KEYWORD_NAMESPACES = (
    (CognitiveNamespace.WEB, ("url", "website", "webpage", "scrape", "browser", "http")),
    (CognitiveNamespace.MEDIA, ("image", "video", "audio", "pdf", "presentation", "spreadsheet", "document", "convert")),
    (CognitiveNamespace.PEOPLE, ("contact", "person", "who is", "colleague", "client contact")),
    (CognitiveNamespace.PROJECTS, ("project", "workspace", "repository", "milestone")),
    (CognitiveNamespace.PREFERENCES, ("prefer", "i like", "i want", "always use", "never use", "don't use", "do not use")),
    (CognitiveNamespace.FINANCE, ("price", "trade", "portfolio", "market", "stock", "position")),
)

NAMESPACED_MEMORY_TYPES = {
    CognitiveNamespace.PREFERENCES: MemoryType.PREFERENCE,
    CognitiveNamespace.PEOPLE: MemoryType.PERSON,
    CognitiveNamespace.PROJECTS: MemoryType.PROJECT,
    CognitiveNamespace.AGENCY: MemoryType.CLIENT,
}


def infer_namespace(*, domain: str = "", intent: str = "", text: str = "") -> CognitiveNamespace:
    """Deterministic namespace inference: explicit keyword signals
    first, then task domain."""
    lowered = (text or "").lower()
    for namespace, keywords in KEYWORD_NAMESPACES:
        if any(keyword in lowered for keyword in keywords):
            return namespace
    if domain:
        mapped = DOMAIN_NAMESPACES.get(domain.lower())
        if mapped is not None:
            return mapped
    return CognitiveNamespace.SYSTEM


@dataclass
class NamespacedHit:
    namespace: CognitiveNamespace
    source: str           # memory | experience | knowledge | skill | tool | external_research
    reference: str
    payload: str
    confidence: float


class NamespaceMemoryRouter:
    """Writes and queries the EXISTING structured memory store through
    cognitive namespaces. Namespace lives in entry tags plus the
    natural type mapping (preferences→PREFERENCE, people→PERSON,
    projects→PROJECT, agency→CLIENT) — no schema change, no new
    database."""

    TAG_PREFIX = "ns:"

    def __init__(self, memory: MemoryManager):
        self.memory = memory

    @classmethod
    def tag_for(cls, namespace: CognitiveNamespace) -> str:
        return f"{cls.TAG_PREFIX}{namespace.value}"

    async def remember(self, namespace: CognitiveNamespace, title: str, content: str, *,
                       summary: str = "", provenance_reference: str = "user statement",
                       confidence: float = 0.6, importance: float = 0.5) -> str:
        """Store knowledge in a cognitive namespace. Structured store
        only — this API never writes .md/.txt files."""
        from app.memory.schemas import MemoryEntry, MemoryProvenance, ProvenanceType

        entry = MemoryEntry(
            title=title,
            content=content,
            summary=summary or content[:180],
            type=NAMESPACED_MEMORY_TYPES.get(namespace, MemoryType.SEMANTIC),
            tags=[self.tag_for(namespace), namespace.value],
            provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference=provenance_reference)],
            confidence=confidence,
            importance=importance,
        )
        stored = await self.memory.remember(entry)
        return stored.id

    async def recall(self, namespace: CognitiveNamespace, query: str, limit: int = 5):
        """Namespace-scoped retrieval through the existing hybrid
        search (tags filter + relevance ranking)."""
        results = await self.memory.search(MemoryQuery(text=query, limit=limit * 3))
        tag = self.tag_for(namespace)
        hits = [item for item in results if tag in (item.memory.tags or [])]
        return hits[:limit]
