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
        the same (subject, predicate, domain) confirms/refreshes it
        instead of duplicating - this is what lets a fact stay 'fresh'
        across repeated research without the store growing unboundedly,
        and keeps each agent's own wiki independent."""
        existing = await self.store.find_existing(fact.subject, fact.predicate, domain=fact.domain)
        if existing is not None:
            prev_value = existing.value
            # Karpathy's contradiction rule: a DIFFERENT value for the same
            # (subject, predicate, domain) is a real discrepancy, NOT a
            # silent overwrite. Flag it, keep the prior value/source, and
            # bump the counter so lint can surface it for review — the
            # conflict is never silently dropped. (Same value = a normal
            # re-confirmation, no flag.)
            if prev_value.strip().lower() != fact.value.strip().lower():
                existing.contradicted = True
                existing.contradiction_count += 1
                prior = list(existing.metadata.get("prior_values", []))
                prior.append({
                    "value": prev_value,
                    "source_url": existing.source_url,
                    "source_title": existing.source_title,
                    "conflicted_at": utc_now().isoformat(),
                })
                existing.metadata["prior_values"] = prior[-5:]
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
                                      confidence: float = 0.55,
                                      domain: str = "general") -> list[KnowledgeFact]:
        """Extracts candidate facts from clean article text (e.g. a
        DefuddleExtractor.ExtractionResult.content) and records every
        one with the real source_url as evidence. Never fabricates -
        only sentences literally present in `text` become facts. `domain`
        tags the facts as belonging to one agent's own wiki."""
        candidates = self.extractor.extract(
            text=text, source_url=source_url, source_title=source_title,
            subject_hint=subject_hint, task_id=task_id, confidence=confidence,
            domain=domain,
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
            tags=[_NAMESPACE_TAG, CognitiveNamespace.KNOWLEDGE.value, fact.subject.lower(), f"wiki:{fact.domain}"],
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

    async def recall(self, subject: str, *, limit: int = 20, domain: str | None = None) -> KnowledgeRecallResult:
        """Ask the knowledge base first. Exact/substring subject match
        via KnowledgeStore; if nothing is found there, falls back to
        the existing FTS5 + embedding MemoryRetriever scoped to the
        knowledge namespace, then resolves any hit back to structured
        facts by subject. When `domain` is given, restrict to ONE
        agent's own wiki (per-agent knowledge base); when omitted,
        search across all wikis (global)."""
        facts = await self.store.by_subject(subject, limit=limit, domain=domain)
        if not facts:
            resolved_subjects = await self.store.search_subjects(subject, limit=5, domain=domain)
            for resolved in resolved_subjects:
                facts.extend(await self.store.by_subject(resolved, limit=limit, domain=domain))
        if not facts:
            results = await self.memory.search(MemoryQuery(text=subject, limit=limit))
            hit_subjects = {
                entity for item in results
                if _NAMESPACE_TAG in (item.memory.tags or [])
                for entity in (item.memory.entities or [])
            }
            # When scoped to a domain, only resolve hits that belong to
            # that domain's wiki.
            for hit_subject in hit_subjects:
                facts.extend(await self.store.by_subject(hit_subject, limit=limit, domain=domain))

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

    async def ask_or_research(self, subject: str, research_fn, *, limit: int = 20,
                              domain: str | None = None) -> KnowledgeRecallResult:
        """Reusable entry point for the task runtime and any other
        caller: 'ask the knowledge base first, browse only if not
        found or stale'. `research_fn` is an async callable taking no
        args that performs the real research/browsing and returns the
        list of newly recorded KnowledgeFact (typically via
        record_facts_from_text) - it is only invoked when recall()
        reports needs_research=True. `domain` scopes the recall (and the
        facts the research records, via the caller's research_fn) to one
        agent's own wiki."""
        result = await self.recall(subject, limit=limit, domain=domain)
        if not result.needs_research:
            return result
        new_facts = await research_fn()
        if new_facts:
            return await self.recall(subject, limit=limit, domain=domain)
        # Research ran but found nothing new; return what we had
        # (possibly stale, possibly empty) rather than pretending success.
        return result

    # -- Karpathy-style wiki audit + cross-reference ---------------------

    async def related(self, subject: str, *, domain: str | None = None, limit: int = 20) -> list[KnowledgeFact]:
        """Karpathy cross-reference: facts in (optionally) one agent's wiki
        that are linked to `subject` by a shared subject token or the same
        predicate — the structured equivalent of a [[wikilink]]. This is
        what turns a pile of facts into a connected knowledge graph that
        compounds, so recalling one subject surfaces its neighbours."""
        return await self.store.related(subject, domain=domain, limit=limit)

    async def lint(self, domain: str | None = None, *, stale_days: int | None = None,
                   low_confidence: float = 0.4) -> dict:
        """Karpathy-style wiki audit/lint for one agent's wiki (or all if
        `domain` is None). Surfaces the problems a human or the client
        should review rather than silently letting weak/conflicting facts
        harden into accepted truth:

          - contradicted: same (subject, predicate) got a DIFFERENT value
            (flagged by record_fact; never silently dropped)
          - stale: last confirmed longer ago than `fresh_after_days`
          - low_confidence: confidence below `low_confidence`
          - orphans: facts with no cross-reference to any other fact
        """
        stale_days = stale_days or self.fresh_after_days
        domains = [domain] if domain else await self.store.namespaces()
        report = {"domains": {}, "totals": {"facts": 0, "contradicted": 0, "stale": 0,
                                            "low_confidence": 0, "orphans": 0}}
        for dom in domains:
            facts = await self.store.facts_in_domain(dom)
            contradicted = [f for f in facts if f.contradicted or f.contradiction_count > 0]
            stale = [f for f in facts if self.store.is_stale(f, stale_days)]
            low = [f for f in facts if f.confidence < low_confidence]
            orphans = []
            for f in facts:
                links = await self.store.related(f.subject, domain=dom, limit=2)
                if not links:
                    orphans.append(f)
            report["domains"][dom] = {
                "facts": len(facts),
                "contradicted": [f.model_dump(mode="json") for f in contradicted],
                "stale": [f.model_dump(mode="json") for f in stale],
                "low_confidence": [f.model_dump(mode="json") for f in low],
                "orphans": [f.model_dump(mode="json") for f in orphans],
            }
            for key in ("facts", "contradicted", "stale", "low_confidence", "orphans"):
                value = report["domains"][dom][key]
                report["totals"][key] += value if isinstance(value, int) else len(value)
        report["stale_days"] = stale_days
        report["low_confidence_threshold"] = low_confidence
        return report
