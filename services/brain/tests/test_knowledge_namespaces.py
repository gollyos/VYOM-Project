"""Per-agent knowledge-base namespace isolation tests. The user's ask:
every distinct agent/task-type (research, coding, email, video, market
data, ...) should have its OWN dedicated knowledge base ('wiki') that
improves and updates independently — NOT all facts mixed into one
shared pool.

Design (added this session via migration v7 knowledge_namespace_v1):
the `knowledge_facts` table gained a `domain` TEXT NOT NULL DEFAULT
'general' column, and the reconfirm key is now (domain, subject_key,
predicate) — so the SAME fact can exist independently in two agents'
wikis without one overwriting the other. KnowledgeStore/KnowledgeService
take a `domain` param and scope reads/writes to it; a domain-less query
is a global (cross-wiki) search.

These tests prove: (1) facts stored under domain A do NOT leak into
domain B, (2) facts in the same domain accumulate/update correctly,
(3) a global query still sees everything, (4) the namespaces() list
reflects the distinct wikis, (5) record_facts_from_text tags facts to
the right wiki.
"""
from __future__ import annotations

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


def _make_fact(subject: str, predicate: str, value: str, domain: str) -> KnowledgeFact:
    return KnowledgeFact(subject=subject, predicate=predicate, value=value, domain=domain)


async def test_facts_do_not_leak_across_domains(knowledge_service):
    """The isolation guarantee: a fact learned by the research agent is
    NOT returned when the coding agent queries its own wiki."""
    await knowledge_service.record_fact(_make_fact("Quantum computing", "is a", "computing paradigm", "research"))
    await knowledge_service.record_fact(_make_fact("Quantum computing", "uses", "qubits", "coding"))

    research = await knowledge_service.recall("Quantum computing", domain="research")
    coding = await knowledge_service.recall("Quantum computing", domain="coding")

    research_predicates = {f.predicate for f in research.facts}
    coding_predicates = {f.predicate for f in coding.facts}
    assert "is a" in research_predicates
    assert "uses" in coding_predicates
    assert "is a" not in coding_predicates, "research facts must not leak into the coding wiki"
    assert "uses" not in research_predicates, "coding facts must not leak into the research wiki"


async def test_global_query_sees_all_wikis(knowledge_service):
    """Without a domain, a global query across ALL wikis still returns
    everything VYOM knows about the subject."""
    await knowledge_service.record_fact(_make_fact("Python", "created by", "Guido van Rossum", "research"))
    await knowledge_service.record_fact(_make_fact("Python", "has", "an interpreter", "coding"))

    global_result = await knowledge_service.recall("Python")
    predicates = {f.predicate for f in global_result.facts}
    assert "created by" in predicates
    assert "has" in predicates


async def test_same_subject_predicate_can_exist_in_two_domains_independently(knowledge_service):
    """The reconfirm key is now (domain, subject_key, predicate), so the
    exact same fact can be learned by two agents without one clobbering
    the other or violating the unique index."""
    await knowledge_service.record_fact(_make_fact("Tauri", "is", "a desktop framework", "research"))
    # Same subject+predicate in the coding wiki must be a THIRD row,
    # not an update-conflict, not a silent overwrite of the research one.
    await knowledge_service.record_fact(_make_fact("Tauri", "is", "a desktop framework", "coding"))

    research = await knowledge_service.recall("Tauri", domain="research")
    coding = await knowledge_service.recall("Tauri", domain="coding")
    assert len(research.facts) == 1
    assert len(coding.facts) == 1


async def test_same_domain_accumulates_and_updates(knowledge_service):
    """Within ONE domain, re-recording the same (subject, predicate)
    confirms/refreshes it (confirmations bump, last_confirmed_at moves)
    rather than duplicating — the 'improves its own wiki' behavior."""
    fact = _make_fact("Postgres", "is", "a database", "research")
    first = await knowledge_service.record_fact(fact)
    assert first.confirmations == 1

    again = KnowledgeFact(
        subject="Postgres", predicate="is", value="a relational database",
        domain="research", confidence=0.9, source_url="https://postgres.org",
    )
    second = await knowledge_service.record_fact(again)
    assert second.confirmations == first.confirmations + 1
    assert second.confidence >= 0.9
    result = await knowledge_service.recall("Postgres", domain="research")
    assert len(result.facts) == 1, "re-recording in the same domain must not duplicate"
    assert result.facts[0].value == "a relational database"


async def test_record_facts_from_text_tags_domain(knowledge_service):
    """The research pipeline's record_facts_from_text(domain='research')
    must stash those facts under the 'research' wiki, not 'general'."""
    text = "The Model Context Protocol (MCP) is a standard for connecting AI models to tools."
    recorded = await knowledge_service.record_facts_from_text(
        text=text, source_url="https://example.com", subject_hint="Model Context Protocol",
        domain="research",
    )
    assert recorded, "expected at least one extracted fact"
    assert all(f.domain == "research" for f in recorded)
    # And the general wiki should NOT contain it.
    general = await knowledge_service.recall("Model Context Protocol", domain="general")
    assert not general.facts


async def test_namespaces_lists_distinct_wikis(knowledge_service):
    await knowledge_service.record_fact(_make_fact("A", "is", "B", "research"))
    await knowledge_service.record_fact(_make_fact("C", "is", "D", "coding"))
    namespaces = await knowledge_service.store.namespaces()
    assert "research" in namespaces
    assert "coding" in namespaces


async def test_default_domain_is_general_for_existing_callers(knowledge_service):
    """Backward compatibility: a fact recorded without an explicit domain
    lands in 'general', so all existing unscoped callers keep working."""
    fact = KnowledgeFact(subject="Universe", predicate="is", value="vast")
    stored = await knowledge_service.record_fact(fact)
    assert stored.domain == "general"
    result = await knowledge_service.recall("Universe", domain="general")
    assert len(result.facts) == 1
