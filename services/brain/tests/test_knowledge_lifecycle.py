"""Tests for the knowledge-fact memory lifecycle (contradiction
auto-resolution, decayed retrieval ranking, value_changed_at) - the
gap named by a viral reel critiquing naive "AI maintains its own
wiki" setups: a contradiction flag that never resolves, and no
distinction between "this was looked at again" and "the value
actually changed".
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

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


# -- effective_confidence decay ----------------------------------------------


def test_a_freshly_confirmed_fact_keeps_full_confidence():
    fact = KnowledgeFact(subject="X", predicate="is", value="Y", confidence=0.8)
    assert fact.effective_confidence() == pytest.approx(0.8, abs=0.01)


def test_a_fact_untouched_for_one_half_life_is_worth_half():
    fact = KnowledgeFact(
        subject="X", predicate="is", value="Y", confidence=0.8,
        last_confirmed_at=utc_now() - timedelta(days=180),
    )
    assert fact.effective_confidence(half_life_days=180) == pytest.approx(0.4, abs=0.02)


def test_effective_confidence_never_mutates_stored_confidence():
    fact = KnowledgeFact(
        subject="X", predicate="is", value="Y", confidence=0.8,
        last_confirmed_at=utc_now() - timedelta(days=400),
    )
    fact.effective_confidence()
    assert fact.confidence == 0.8


# -- contradiction auto-resolution -------------------------------------------


@pytest.mark.asyncio
async def test_a_contradiction_flag_clears_after_enough_agreeing_reconfirmations(knowledge_service):
    """The exact reel-named gap: a contradiction must not stay flagged
    forever once the world settles and every later source agrees
    again."""
    await knowledge_service.record_fact(KnowledgeFact(
        subject="Deploy pipeline", predicate="runs on", value="shared runner pool",
        domain="general", source_url="https://a.example/1",
    ))
    # A conflicting value creates the contradiction.
    contradicted = await knowledge_service.record_fact(KnowledgeFact(
        subject="Deploy pipeline", predicate="runs on", value="dedicated runner",
        domain="general", source_url="https://b.example/1",
    ))
    assert contradicted.contradicted is True
    assert contradicted.contradiction_count == 1

    # Three later sources agree with the CURRENT value.
    for index in range(3):
        result = await knowledge_service.record_fact(KnowledgeFact(
            subject="Deploy pipeline", predicate="runs on", value="dedicated runner",
            domain="general", source_url=f"https://c.example/{index}",
        ))

    assert result.contradicted is False
    # The history is NOT erased just because it auto-resolved.
    assert result.contradiction_count == 1
    assert result.metadata.get("prior_values")


@pytest.mark.asyncio
async def test_a_new_contradiction_resets_the_reconfirmation_counter(knowledge_service):
    await knowledge_service.record_fact(KnowledgeFact(
        subject="API version", predicate="is", value="v1", domain="general",
    ))
    await knowledge_service.record_fact(KnowledgeFact(
        subject="API version", predicate="is", value="v2", domain="general",
    ))
    # Two agreements, not yet enough to auto-resolve.
    await knowledge_service.record_fact(KnowledgeFact(
        subject="API version", predicate="is", value="v2", domain="general",
    ))
    partially_confirmed = await knowledge_service.record_fact(KnowledgeFact(
        subject="API version", predicate="is", value="v2", domain="general",
    ))
    assert partially_confirmed.contradicted is True
    assert partially_confirmed.consistent_reconfirmations == 2

    # A NEW contradiction (a third distinct value) must reset the count,
    # not silently accumulate toward auto-resolving the WRONG history.
    re_contradicted = await knowledge_service.record_fact(KnowledgeFact(
        subject="API version", predicate="is", value="v3", domain="general",
    ))
    assert re_contradicted.contradicted is True
    assert re_contradicted.consistent_reconfirmations == 0
    assert re_contradicted.contradiction_count == 2


@pytest.mark.asyncio
async def test_value_changed_at_advances_only_on_a_real_value_change(knowledge_service):
    first = await knowledge_service.record_fact(KnowledgeFact(
        subject="Team size", predicate="is", value="5", domain="general",
    ))
    first_changed_at = first.value_changed_at

    # Re-confirming the SAME value must not move value_changed_at, even
    # though last_confirmed_at does.
    reconfirmed = await knowledge_service.record_fact(KnowledgeFact(
        subject="Team size", predicate="is", value="5", domain="general",
    ))
    assert reconfirmed.value_changed_at == first_changed_at
    assert reconfirmed.last_confirmed_at >= first.last_confirmed_at

    # A genuinely different value DOES move it.
    changed = await knowledge_service.record_fact(KnowledgeFact(
        subject="Team size", predicate="is", value="7", domain="general",
    ))
    assert changed.value_changed_at > first_changed_at


# -- recall() ranks by decayed confidence, not raw stored confidence --------


@pytest.mark.asyncio
async def test_recall_ranks_recently_confirmed_facts_above_stale_higher_confidence_ones(knowledge_service):
    """recall() must return the FRESH fact first even though a
    differently-worded, higher-raw-confidence fact about the same
    subject is more stale - ranking by effective_confidence()
    (decayed), not stored confidence."""
    old = await knowledge_service.record_fact(KnowledgeFact(
        subject="Vendor SLA", predicate="typical response time", value="24 hours",
        domain="general", confidence=0.9,
    ))
    # Backdate its last_confirmed_at directly via the store (record_fact
    # always sets "now" on write, so simulate real staleness the same
    # way production data actually ages: writing it, then pushing the
    # confirmed timestamp back).
    old.last_confirmed_at = utc_now() - timedelta(days=400)
    await knowledge_service.store.save(old)

    await knowledge_service.record_fact(KnowledgeFact(
        subject="Vendor SLA", predicate="current response time", value="4 hours",
        domain="general", confidence=0.6,
    ))

    result = await knowledge_service.recall("Vendor SLA", domain="general")
    assert result.facts[0].value == "4 hours"
