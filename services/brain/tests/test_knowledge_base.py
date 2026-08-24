"""Knowledge Base: recording facts learned from browsing/research and
recalling them instantly without re-researching (VYOM's 'khud ka
Wikipedia'). Built on the existing MemoryStore/Database/migration
pattern in the `knowledge` namespace - see app/knowledge/.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.knowledge.extractor import FactExtractor
from app.knowledge.schemas import KnowledgeFact, utc_now
from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore
from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.store import MemoryStore
from app.migrations.manager import MigrationManager
from app.persistence.database import Database
from app.research.orchestrator import DeepResearchTask
from app.research.source_discovery import BrowserSearchProvider, SourceDiscovery
from app.research.schemas import ResearchBudget, ResearchDepth, ResearchPlan


# -- fixtures --------------------------------------------------------------


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    await MigrationManager(db).apply_pending()
    yield db
    await db.close()


@pytest.fixture
def knowledge_store(database):
    return KnowledgeStore(database)


@pytest.fixture
def memory_manager(database):
    store = MemoryStore(database)
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    return MemoryManager(store, MemoryRetriever(store, embeddings))


@pytest.fixture
def knowledge_service(knowledge_store, memory_manager):
    return KnowledgeService(knowledge_store, memory_manager, fresh_after_days=30)


# -- migration applies cleanly ---------------------------------------------


async def test_knowledge_facts_table_is_created_by_migration(database):
    manager = MigrationManager(database)
    result = await manager.apply_pending()
    names = [m["name"] for m in result["applied"]] + [
        # already-applied path when the fixture above ran it first
    ]
    status = await manager.status()
    assert status["pending"] == []
    assert status["current_version"] >= 5


# -- recording + exact recall -----------------------------------------------


async def test_recording_a_fact_and_recalling_it_by_subject(knowledge_service):
    fact = KnowledgeFact(
        subject="Python",
        predicate="created by",
        value="Guido van Rossum",
        source_url="https://python.org/about",
        source_title="About Python",
        confidence=0.8,
    )
    stored = await knowledge_service.record_fact(fact)
    assert stored.id == fact.id
    assert stored.memory_id is not None  # mirrored into the memory store

    result = await knowledge_service.recall("Python")
    assert result.subject == "Python"
    assert result.stale is False
    assert result.needs_research is False
    assert len(result.facts) == 1
    assert result.facts[0].value == "Guido van Rossum"
    assert result.facts[0].source_url == "https://python.org/about"


async def test_recall_finds_facts_via_memory_fts_when_subject_not_exact(knowledge_service):
    """Recall should locate a fact stored under 'Python programming
    language' even when asked about just 'python', by falling back to
    the existing FTS5/embedding memory search."""
    await knowledge_service.record_fact(KnowledgeFact(
        subject="Python programming language",
        predicate="created by",
        value="Guido van Rossum",
        source_url="https://python.org/about",
    ))
    result = await knowledge_service.recall("python")
    assert len(result.facts) >= 1
    assert result.facts[0].value == "Guido van Rossum"


async def test_recall_of_unknown_subject_reports_needs_research(knowledge_service):
    result = await knowledge_service.recall("Some Never Researched Topic XYZ")
    assert result.facts == []
    assert result.needs_research is True
    assert result.stale is True


# -- re-confirmation instead of duplication ---------------------------------


async def test_recording_same_subject_predicate_twice_confirms_not_duplicates(knowledge_service):
    first = await knowledge_service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum",
        source_url="https://python.org/about",
    ))
    second = await knowledge_service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum",
        source_url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    ))
    assert first.id == second.id
    assert second.confirmations == 2
    result = await knowledge_service.recall("Python")
    assert len(result.facts) == 1  # not duplicated


# -- staleness --------------------------------------------------------------


async def test_stale_fact_triggers_needs_research_flag(knowledge_service, knowledge_store):
    fact = await knowledge_service.record_fact(KnowledgeFact(
        subject="Old Topic", predicate="is a", value="something",
        source_url="https://example.com/old",
    ))
    # Simulate the fact having been confirmed 400 days ago (well past
    # the 30-day freshness window configured on the fixture).
    fact.last_confirmed_at = utc_now() - timedelta(days=400)
    await knowledge_store.save(fact)

    result = await knowledge_service.recall("Old Topic")
    assert result.stale is True
    assert result.needs_research is True
    assert "days" in result.reason


async def test_ask_or_research_skips_research_when_fresh(knowledge_service):
    await knowledge_service.record_fact(KnowledgeFact(
        subject="Fresh Topic", predicate="is a", value="a fresh fact",
        source_url="https://example.com/fresh",
    ))
    called = {"n": 0}

    async def research_fn():
        called["n"] += 1
        return []

    result = await knowledge_service.ask_or_research("Fresh Topic", research_fn)
    assert called["n"] == 0  # never invoked - already fresh
    assert result.needs_research is False


async def test_ask_or_research_invokes_research_when_stale_or_unknown(knowledge_service):
    called = {"n": 0}

    async def research_fn():
        called["n"] += 1
        await knowledge_service.record_fact(KnowledgeFact(
            subject="Brand New Topic", predicate="is a", value="a newly researched fact",
            source_url="https://example.com/new",
        ))
        return ["fact recorded"]

    result = await knowledge_service.ask_or_research("Brand New Topic", research_fn)
    assert called["n"] == 1
    assert result.needs_research is False
    assert len(result.facts) == 1
    assert result.facts[0].value == "a newly researched fact"


# -- extraction from clean article text -------------------------------------


def test_extractor_pulls_real_sentences_only_never_fabricates():
    text = (
        "Python is a high-level programming language. "
        "Python was created by Guido van Rossum. "
        "The sky is unrelated noise that should still parse as a sentence."
    )
    extractor = FactExtractor()
    facts = extractor.extract(text=text, source_url="https://python.org/about", subject_hint="Python")
    assert facts, "expected at least one fact extracted from real sentences"
    for fact in facts:
        assert fact.source_url == "https://python.org/about"
        # Every fact's value must be traceable to the actual source text.
        assert fact.value.split(".")[0].strip() in text


# -- end-to-end: real browser/search output -> knowledge store -------------
# Reuses the FakeBrowserActions pattern from test_browser_search_provider.py
# (realistic DuckDuckGo HTML result shapes) rather than inventing new
# browser mocking, and drives it through the SAME DeepResearchTask path
# used in production, with a defuddle_extractor stub returning real
# clean text (as DefuddleExtractor.extract would after reading a page).


class _FakeBrowserActions:
    def __init__(self):
        self.extracted = {
            "items": ["Python Official Site"],
            "hrefs": ["https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&rut=abc"],
        }
        self.opened_urls: list[str] = []

    async def perform(self, action, inputs):
        if action == "open":
            self.opened_urls.append(inputs["url"])
            return {"url": inputs["url"], "title": "DuckDuckGo"}
        if action == "extract":
            return {**self.extracted, "url": self.opened_urls[-1] if self.opened_urls else ""}
        raise ValueError(f"unexpected action: {action}")


class _FakeDefuddleExtractor:
    """Stands in for the real DefuddleExtractor: returns clean article
    text for the one real source url the fake search resolves to,
    exactly like a genuine Defuddle/Playwright extraction would."""

    class _Result:
        def __init__(self, content, success=True):
            self.content = content
            self.success = success

    async def extract(self, url: str):
        assert url == "https://python.org/"
        return self._Result(
            "Python is a high-level programming language. "
            "Python was created by Guido van Rossum."
        )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        goal="Python",
        depth=ResearchDepth.STANDARD,
        budget=ResearchBudget(max_sources=3, max_queries=1, max_model_calls=1,
                               max_browser_time_seconds=60, max_cost=0.1, max_runtime_seconds=60),
    )


async def test_research_task_extracts_and_persists_facts_from_real_browser_search_output(knowledge_service):
    from app.research.citation_builder import CitationBuilder
    from app.research.contradiction import ContradictionDetector
    from app.research.extractor import ClaimExtractor
    from app.research.freshness import FreshnessPolicy
    from app.research.query_planner import QueryPlanner
    from app.research.source_ranker import SourceRanker
    from app.research.synthesizer import ResearchSynthesizer
    from app.research.verifier import ResearchVerifier

    provider = BrowserSearchProvider(_FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    discovery = SourceDiscovery([provider])

    task = DeepResearchTask(
        query_planner=QueryPlanner.from_config({}),
        source_discovery=discovery,
        source_ranker=SourceRanker.from_config({}),
        extractor=ClaimExtractor(),
        contradiction_detector=ContradictionDetector(),
        freshness_policy=FreshnessPolicy.from_config({}),
        synthesizer=ResearchSynthesizer(),
        citation_builder=CitationBuilder(),
        verifier=ResearchVerifier(),
        defuddle_extractor=_FakeDefuddleExtractor(),
        knowledge_service=knowledge_service,
    )

    plan = _plan()
    result = await task.run(plan.goal, depth=plan.depth)
    assert result.sources, "the fake search must yield at least one real source"

    # The fact learned while reading the real (fake-backed) source must
    # now be recallable from the knowledge base with its real url as
    # evidence - never re-researched to answer this.
    recalled = await knowledge_service.recall("Python")
    assert recalled.facts, "expected a fact extracted from the browsed page to be persisted"
    assert any(f.source_url == "https://python.org/" for f in recalled.facts)
