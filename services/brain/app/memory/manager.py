from __future__ import annotations

from datetime import datetime, timezone

from .consolidation import MemoryConsolidator
from .provenance import explain_provenance
from .relationships import RelationshipManager
from .retrieval import MemoryRetriever
from .schemas import MemoryEntry, MemoryQuery, MemorySearchResult, VerificationState
from .store import MemoryStore


class MemoryManager:
    def __init__(self, store: MemoryStore, retriever: MemoryRetriever):
        self.store = store
        self.retriever = retriever
        self.relationships = RelationshipManager(store)
        self.consolidator = MemoryConsolidator()

    async def remember(self, memory: MemoryEntry) -> MemoryEntry:
        return await self.store.save(memory)

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        return await self.retriever.search(query)

    async def inspect(self, memory_id: str) -> dict | None:
        memory = await self.store.get(memory_id)
        if not memory or memory.deleted_at is not None:
            # A forgotten memory is out of the user-facing view; the row
            # itself is preserved for history queries at the store level.
            return None
        return {"memory": memory.model_dump(mode="json"), "provenance": explain_provenance(memory)}

    async def forget(self, memory_id: str) -> bool:
        """Soft-forget (tombstone). The memory is never erased - see
        MemoryStore.forget for why this is deliberate."""
        return await self.store.forget(memory_id)

    async def history(self, memory_id: str) -> list[MemoryEntry]:
        """Every prior version of a memory, oldest first - the
        append-only answer to 'what did this say ten years ago'."""
        return await self.store.history(memory_id)

    async def purge(self, memory_id: str) -> bool:
        """True erasure. Deliberate maintenance only, never wired to the
        API or voice 'forget'."""
        return await self.store.purge(memory_id)

    async def update(self, memory_id: str, **changes) -> MemoryEntry:
        memory = await self.store.get(memory_id, touch=False)
        if not memory:
            raise KeyError(memory_id)
        allowed = {"title", "content", "summary", "entities", "tags", "importance", "confidence", "sensitivity", "verification_state"}
        for key, value in changes.items():
            if key not in allowed:
                raise ValueError(f"Memory field cannot be updated: {key}")
            setattr(memory, key, value)
        memory.updated_at = datetime.now(timezone.utc)
        return await self.store.save(memory)

    async def correct(self, memory_id: str, replacement: MemoryEntry) -> MemoryEntry:
        previous = await self.store.get(memory_id, touch=False)
        if not previous:
            raise KeyError(memory_id)
        previous.verification_state = VerificationState.SUPERSEDED
        previous.confidence = min(previous.confidence, 0.1)
        await self.store.save(previous)
        replacement.supersedes = previous.id
        return await self.store.save(replacement)
