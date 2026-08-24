from __future__ import annotations

from app.memory.namespaces import CognitiveNamespace
from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryQuery, MemoryType, ProvenanceType
from app.memory.manager import MemoryManager

from .extractor import FactExtractor
from .schemas import KnowledgeFact, KnowledgeRecallResult, utc_now
from .store import KnowledgeStore

_NAMESPACE_TAG = f"ns:{CognitiveNamespace.KNOWLEDGE.value}"


class KnowledgeService:
    """VYOM's 'khud ka Wikipedia': the reusable service other code
    (task runtime, research pipeline, API) calls to record facts
    learned from browsing/research and to recall them instantly
    without re-researching.

    Built entirely on the EXISTING stores:
      - KnowledgeStore (new `knowledge_facts` table via a real
        Migration) for exact subject/predicate lookups and staleness.
      - MemoryStore/MemoryManager (existing FTS5 + embedding search)
        for fuzzy/semantic recall, via a mirrored MemoryEntry per fact
        tagged ns:knowledge - so a query like "who made python" can
        find a fact stored under subject "Python" without an exact
        string match.
    """

    def __init__(self, store: KnowledgeStore, memory: MemoryManager,
                 extractor: FactExtractor | None = None, *, fresh_after_days: int = 30):
        self.store = store
        self.memory = memory
        self.extractor = extractor or FactExtractor()
        #: Facts older than this (by last_confirmed_at) are still
        #: returned but flagged stale/needs_research so a caller can
        #: choose to refresh in the background instead of blocking.
        self.fresh_after_days = fresh_after_days

    # -- recording ---------------------------------------------------

    async def record_fact(self, fact: KnowledgeFact) -> KnowledgeFact:
        """Record one fact with its real source evidence. Re-recording
        the same (subject, predicate) confirms/refreshes it instead of
        duplicating - this is what lets a fact stay 'fresh' across
        repeated research without the store growing unboundedly."""
        existing = await self.store.find_existing(fact.subject, fact.predicate)
        if existing is not None:
            existing.value = fact.value
            existing.confidence = max(existing.confidence, fact.confidence)
            if fact.source_url:
                existing.source_url = fact.source_url
                existing.source_title = fact.source_title
            existing.last_confirmed_at = utc_now()
            existing.confirmations += 1
            existing.task_id = fact.task_id or existing.task_id
            stored = await self.store.save(existing)
        else:
            stored = await self.store.save(fact)
            memory_id = await self._mirror_to_memory(stored)
            stored.memory_id = memory_id
            stored = await self.store.save(stored)
        return stored

    async def record_facts_from_text(self, *, text: str, source_url: str | None,
                                      source_title: str | None = None,
                                      subject_hint: str | None = None,
                                      task_id: str | None = None,
                                      confidence: float = 0.55) -> list[KnowledgeFact]:
        """Extracts candidate facts from clean article text (e.g. a
        DefuddleExtractor.ExtractionResult.content) and records every
        one with the real source_url as evidence. Never fabricates -
        only sentences literally present in `text` become facts."""
        candidates = self.extractor.extract(
            text=text, source_url=source_url, source_title=source_title,
            subject_hint=subject_hint, task_id=task_id, confidence=confidence,
        )
        recorded = []
        for candidate in candidates:
            recorded.append(await self.record_fact(candidate))
        return recorded

    async def _mirror_to_memory(self, fact: KnowledgeFact) -> str:
        entry = MemoryEntry(
            title=f"{fact.subject} — {fact.predicate}",
            content=fact.as_sentence(),
            summary=fact.as_sentence()[:180],
            type=MemoryType.SEMANTIC,
            tags=[_NAMESPACE_TAG, CognitiveNamespace.KNOWLEDGE.value, fact.subject.lower()],
            entities=[fact.subject],
            source=fact.source_url,
            provenance=[MemoryProvenance(
                type=ProvenanceType.EXTERNAL_SOURCE if fact.source_url else ProvenanceType.AGENT_OBSERVATION,
                reference=fact.source_title or fact.source_url or "research task",
                source_url=fact.source_url,
                task_id=fact.task_id,
            )],
            confidence=fact.confidence,
            importance=0.4,
        )
        stored = await self.memory.remember(entry)
        return stored.id

    # -- recall --------------------------------------------------------

    async def recall(self, subject: str, *, limit: int = 20) -> KnowledgeRecallResult:
        """Ask the knowledge base first. Exact/substring subject match
        via KnowledgeStore; if nothing is found there, falls back to
        the existing FTS5 + embedding MemoryRetriever scoped to the
        knowledge namespace, then resolves any hit back to structured
        facts by subject."""
        facts = await self.store.by_subject(subject, limit=limit)
        if not facts:
            resolved_subjects = await self.store.search_subjects(subject, limit=5)
            for resolved in resolved_subjects:
                facts.extend(await self.store.by_subject(resolved, limit=limit))
        if not facts:
            results = await self.memory.search(MemoryQuery(text=subject, limit=limit))
            hit_subjects = {
                entity for item in results
                if _NAMESPACE_TAG in (item.memory.tags or [])
                for entity in (item.memory.entities or [])
            }
            for hit_subject in hit_subjects:
                facts.extend(await self.store.by_subject(hit_subject, limit=limit))

        if not facts:
            return KnowledgeRecallResult(
                subject=subject, facts=[], stale=True, needs_research=True,
                reason="no facts known for this subject",
            )

        stalest = max(facts, key=lambda f: f.last_confirmed_at)
        is_stale = self.store.is_stale(stalest, self.fresh_after_days)
        return KnowledgeRecallResult(
            subject=subject,
            facts=facts,
            stale=is_stale,
            needs_research=is_stale,
            reason="fresh, no research needed" if not is_stale else
                   f"facts are older than {self.fresh_after_days} days; a refresh is recommended",
        )

    async def ask_or_research(self, subject: str, research_fn, *, limit: int = 20) -> KnowledgeRecallResult:
        """Reusable entry point for the task runtime and any other
        caller: 'ask the knowledge base first, browse only if not
        found or stale'. `research_fn` is an async callable taking no
        args that performs the real research/browsing and returns the
        list of newly recorded KnowledgeFact (typically via
        record_facts_from_text) - it is only invoked when recall()
        reports needs_research=True."""
        result = await self.recall(subject, limit=limit)
        if not result.needs_research:
            return result
        new_facts = await research_fn()
        if new_facts:
            return await self.recall(subject, limit=limit)
        # Research ran but found nothing new; return what we had
        # (possibly stale, possibly empty) rather than pretending success.
        return result
