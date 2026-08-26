from __future__ import annotations

from datetime import datetime, timezone

from .auto_linker import find_link_candidates
from .consolidation import MemoryConsolidator
from .provenance import explain_provenance
from .relationships import RelationshipManager
from .retrieval import MemoryRetriever
from .schemas import MemoryEntry, MemoryQuery, MemorySearchResult, RelationType, VerificationState
from .store import MemoryStore


class MemoryManager:
    def __init__(self, store: MemoryStore, retriever: MemoryRetriever):
        self.store = store
        self.retriever = retriever
        self.relationships = RelationshipManager(store)
        self.consolidator = MemoryConsolidator()

    async def remember(self, memory: MemoryEntry) -> MemoryEntry:
        saved = await self.store.save(memory)
        await self._auto_link(saved)
        return saved

    async def _auto_link(self, memory: MemoryEntry) -> None:
        """Connect a newly-saved memory to real, concretely related
        memories (see auto_linker.py) - this is what turns the
        markdown vault from isolated files into an actual knowledge
        graph, and what a later vault re-render shows as
        [[wikilinks]]. Best-effort: a linking failure must never fail
        the save that already succeeded."""
        try:
            candidates = await self.retriever.search(MemoryQuery(text=memory.title, limit=40))
            others = [hit.memory for hit in candidates if hit.memory.id != memory.id]
            linked = find_link_candidates(memory, others)
            existing = await self.store.relationships(memory.id, relation=RelationType.RELATED_TO.value)
            already_linked_ids = {rel.target_id for rel in existing} | {rel.source_id for rel in existing}
            for other in linked:
                if other.id in already_linked_ids:
                    continue
                await self.relationships.connect(memory.id, other.id, RelationType.RELATED_TO)
            if linked:
                # Re-render BOTH files so the link is visible from
                # either side (Obsidian shows backlinks automatically
                # from a single directed edge, but this vault is
                # plain markdown read by tools that don't compute
                # backlinks - each file states its own outgoing links
                # explicitly instead of relying on a reader to infer
                # them).
                if self.store.vault is not None and self.store.vault.enabled:
                    all_related = await self.store.relationships(memory.id, relation=RelationType.RELATED_TO.value)
                    self.store.vault.write(memory, related=await self._resolve_related(all_related, memory.id))
                    for other in linked:
                        other_related = await self.store.relationships(other.id, relation=RelationType.RELATED_TO.value)
                        self.store.vault.write(other, related=await self._resolve_related(other_related, other.id))
        except Exception:
            pass

    async def _resolve_related(self, relationships, memory_id: str) -> list[MemoryEntry]:
        other_ids = [
            rel.target_id if rel.source_id == memory_id else rel.source_id
            for rel in relationships
        ]
        resolved = []
        for other_id in other_ids:
            other = await self.store.get(other_id, touch=False)
            if other is not None:
                resolved.append(other)
        return resolved

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
