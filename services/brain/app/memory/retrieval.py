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
            max_sensitivity=query.max_sensitivity,
            verification_states=query.verification_states or None,
        )
        query_tokens = set(re.findall(r"[a-z0-9_]+", query.text.lower()))
        query_embedding = await self.embeddings.embed(query.text) if query.text else None
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
                semantic = cosine_similarity(query_embedding, await self.embeddings.embed(haystack))
            relationships = await self.store.relationships(memory.id)
            relation_score = min(1.0, len(relationships) / 4)
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
