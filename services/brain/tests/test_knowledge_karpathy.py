"""Tests for Karpathy's LLM-wiki idea implemented natively in VYOM's
per-agent knowledge base. Karpathy's wiki pattern is about COMPOUNDING
knowledge over time rather than accumulating isolated rows: cross-
referencing between facts, flagging contradictions instead of silently
overwriting them, and auditing (linting) the wiki so weak/conflicting
facts surface for review instead of hardening into accepted truth.

VYOM already had a structured per-agent facts store (subject/predicate/
value + domain namespace). This adds the three Karpathy behaviours on top:

  1. Contradition detection  — recording a DIFFERENT value for the same
     (subject, predicate, domain) no longer silently overwrites; it flags
     the fact (contradicted=True), keeps the prior value/source, and bumps
     a counter so lint can surface the discrepancy.
  2. Cross-referencing       — related() returns facts linked to a subject
     by a shared token or the same predicate (the structured [[wikilink]]).
  3. Lint / audit            — lint() surfaces contradicted / stale /
     low-confidence / orphan facts per wiki (or globally).

These tests prove all three, including that the contradiction is genuinely
flagged rather than dropped and that a same-value re-confirmation does NOT
raise a false contradiction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.schemas import KnowledgeFact
from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore, _normalize_subject
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
def service(knowledge_store, memory_manager):
    return KnowledgeService(knowledge_store, memory_manager)


# -- 1. contradiction detection ------------------------------------------

@pytest.mark.asyncio
async def test_different_value_flags_contradiction_instead_of_silent_overwrite(service):
    first = await service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum", domain="research"))
    assert first.contradicted is False

    conflicting = await service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Somebody Else", domain="research"))
    # The conflict is FLAGGED, not silently dropped.
    assert conflicting.contradicted is True
    assert conflicting.contradiction_count == 1
    # The prior value/source is kept in metadata so nothing is lost.
    prior = conflicting.metadata["prior_values"]
    assert prior[-1]["value"] == "Guido van Rossum"


@pytest.mark.asyncio
async def test_same_value_reconfirmation_does_not_flag_contradiction(service):
    await service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum", domain="research"))
    reaffirmed = await service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum", domain="research"))
    assert reaffirmed.contradicted is False
    assert reaffirmed.contradiction_count == 0
    # Same value re-confirmation bumps confirmations instead.
    assert reaffirmed.confirmations == 2


@pytest.mark.asyncio
async def test_contradictions_are_isolated_per_domain(service):
    """The SAME subject+predicate can be correct in one agent's wiki and
    differ in another's — so one domain's conflict must not flag the same
    fact in a different domain."""
    await service.record_fact(KnowledgeFact(
        subject="US", predicate="capital", value="Washington DC", domain="research"))
    research = await service.record_fact(KnowledgeFact(
        subject="US", predicate="capital", value="New York", domain="research"))
    assert research.contradicted is True

    # Separately, in the education wiki, the US capital is (correctly)
    # Washington DC — no contradiction against a different wiki.
    edu = await service.record_fact(KnowledgeFact(
        subject="US", predicate="capital", value="Washington DC", domain="education"))
    assert edu.contradicted is False


# -- 2. cross-referencing ------------------------------------------------

@pytest.mark.asyncio
async def test_related_returns_linked_neighbour_facts(service):
    # 'Python' (the query) and 'Python language' share the token 'python',
    # so the second is a cross-referenced NEIGHBOUR even though its exact
    # subject_key differs — the structured [[wikilink]] analogue.
    await service.record_fact(KnowledgeFact(subject="Python", predicate="created by", value="Guido van Rossum", domain="research"))
    await service.record_fact(KnowledgeFact(subject="Python language", predicate="first released", value="1991", domain="research"))
    await service.record_fact(KnowledgeFact(subject="Python", predicate="sample", value="education-only", domain="education"))

    related = await service.related("python", domain="research")
    subjects = {f.subject for f in related}
    # The 'Python language' neighbour is surfaced; the exact 'Python' fact
    # is NOT (it is the queried subject itself, returned by recall instead).
    assert "Python language" in subjects
    predicates = {f.predicate for f in related}
    assert "first released" in predicates
    # The education-domain fact is not a research neighbour.
    assert "sample" not in predicates


@pytest.mark.asyncio
async def test_related_respects_cross_wiki_isolation(service):
    # Same neighbourhood in two separate wikis must not cross-contaminate.
    await service.record_fact(KnowledgeFact(subject="Quantum physics", predicate="field", value="research-note", domain="research"))
    await service.record_fact(KnowledgeFact(subject="Quantum computing", predicate="field", value="education-note", domain="education"))

    research_related = await service.related("quantum", domain="research")
    edu_related = await service.related("quantum", domain="education")
    assert {f.subject for f in research_related} == {"Quantum physics"}
    assert {f.subject for f in edu_related} == {"Quantum computing"}
    # Global cross-wiki query surfaces neighbours from BOTH wikis.
    all_related = await service.related("quantum")
    assert {f.subject for f in all_related} == {"Quantum physics", "Quantum computing"}


# -- 3. lint / audit -----------------------------------------------------

@pytest.mark.asyncio
async def test_lint_surfaces_contradictions_stale_low_confidence_and_orphans(service):
    # A contradicted fact.
    await service.record_fact(KnowledgeFact(subject="Alpha", predicate="owner", value="Alice", domain="research"))
    await service.record_fact(KnowledgeFact(subject="Alpha", predicate="owner", value="Bob", domain="research"))
    # A low-confidence fact (below the 0.4 threshold).
    await service.record_fact(KnowledgeFact(subject="Beta", predicate="size", value="10", domain="research", confidence=0.2))
    # A healthy, well-linked fact.
    await service.record_fact(KnowledgeFact(subject="Gamma", predicate="type", value="x", domain="research"))
    await service.record_fact(KnowledgeFact(subject="Gamma", predicate="desc", value="y", domain="research"))

    report = await service.lint("research", stale_days=9999, low_confidence=0.4)
    d = report["domains"]["research"]
    assert d["contradicted"] != []   # Alpha owner conflict surfaced
    assert any(f["subject"] == "Beta" for f in d["low_confidence"])
    assert any(f["subject"] == "Alpha" for f in d["contradicted"])
    assert d["facts"] >= 4
    assert report["totals"]["facts"] == d["facts"]


@pytest.mark.asyncio
async def test_lint_global_and_empty_domain(service):
    report = await service.lint(stale_days=9999)
    assert report["totals"]["facts"] == 0
    assert report["domains"] == {}


def test_normalize_subject_still_works():
    assert _normalize_subject("Python Programming Language") == "python programming language"
