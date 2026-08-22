from __future__ import annotations

import re

from .embeddings import EmbeddingProvider, cosine_similarity
from .relevance import relevance_score
from .schemas import MemoryQuery, MemorySearchResult, VerificationState
from .store import MemoryStore


class MemoryRetriever:
    def __init__(self, store: MemoryStore, embeddings: EmbeddingProvider):
        self.store = store
        self.embeddings = embeddings

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        # FTS first: a full-text MATCH finds a decade-old record at any
        # scale in milliseconds; the structured candidate window alone
        # made old records unreachable once newer rows existed. When FTS
        # has no hits (or is unavailable) the structured path stands.
        fts_ids: list[str] | None = None
        if query.text:
            fts_ids = await self.store.search_fts(query.text)
        candidates = await self.store.list(
            types=query.types or None,
            project_id=query.project_id,
            client_id=query.client_id,
            agent_id=query.agent_id,
            entities=query.entities or None,
            sources=query.sources or None,
            created_after=query.created_after,
            created_before=query.created_before,
            include_expired=query.include_expired,
            ids=fts_ids,
            max_sensitivity=query.max_sensitivity,
            verification_states=query.verification_states or None,
            limit=2000 if fts_ids else 500,
        )
        query_tokens = set(re.findall(r"[a-z0-9_]+", query.text.lower()))
        query_embedding = await self.embeddings.embed(query.text) if query.text else None
        # ONE relationship query for the whole candidate set, not one per
        # candidate: N+1 lookups do not survive a decade of memories.
        counts = await self.store.relationship_counts([memory.id for memory in candidates])
        ranked: list[MemorySearchResult] = []
        for memory in candidates:
            if (
                memory.verification_state == VerificationState.SUPERSEDED
                and not query.include_superseded
            ):
                continue
            haystack = " ".join([memory.title, memory.summary, memory.content, *memory.tags, *memory.entities]).lower()
            memory_tokens = set(re.findall(r"[a-z0-9_]+", haystack))
            keyword = len(query_tokens & memory_tokens) / max(len(query_tokens), 1) if query_tokens else 0.4
            semantic = 0.0
            if query_embedding is not None:
                embed_memory = getattr(self.embeddings, "embed_memory", None)
                memory_embedding = (
                    await embed_memory(memory, haystack) if embed_memory
                    else await self.embeddings.embed(haystack)
                )
                semantic = cosine_similarity(query_embedding, memory_embedding)
            relation_score = min(1.0, counts.get(memory.id, 0) / 4)
            score, reasons = relevance_score(
                memory,
                keyword_score=keyword,
                semantic_score=semantic,
                relationship_score=relation_score,
            )
            if query.text and keyword == 0 and semantic < 0.05:
                continue
            ranked.append(MemorySearchResult(memory=memory, score=score, reasons=reasons))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: query.limit]
