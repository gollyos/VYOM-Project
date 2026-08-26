"""Tests for MemoryRetriever.search's Devanagari/Unicode tokenization
fix (app/memory/retrieval.py) - a Hindi-only query used to produce an
EMPTY query_tokens set (the old [a-z0-9_]+ pattern only matched Latin
script), which made `keyword` silently fall through to its 0.4 default
regardless of actual overlap - so completely unrelated old memories
(e.g. stale "Solar System" research facts) surfaced for ANY Hindi
conversational statement, a real bug observed in production.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryQuery, MemoryType, ProvenanceType
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.migrations.manager import MigrationManager


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    await MigrationManager(db).apply_pending()
    yield db
    await db.close()


@pytest.fixture
def store(database):
    return MemoryStore(database)


@pytest.fixture
def retriever(database, store):
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    return MemoryRetriever(store, embeddings)


async def _save_solar_system_memory(store: MemoryStore) -> MemoryEntry:
    entry = MemoryEntry(
        type=MemoryType.SEMANTIC,
        title="Completed: Solar system research",
        content="Many objects in the Solar System do not orbit the Sun directly and are instead natural satellites",
        summary="Many objects in the Solar System do not orbit the Sun directly",
        entities=[], tags=["conversation"],
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference="test")],
        importance=0.5, confidence=0.55,
    )
    await store.save(entry)
    return entry


@pytest.mark.asyncio
async def test_unrelated_hindi_query_does_not_surface_an_english_memory_with_zero_overlap(store, retriever):
    """The exact production bug: a Hindi conversational statement with
    zero real keyword overlap with an old English memory must not
    surface that memory just because Devanagari tokens weren't counted
    at all."""
    await _save_solar_system_memory(store)

    results = await retriever.search(MemoryQuery(
        text="मैं सारी बातें नहीं बोल रहा हूं जो मेन टॉपिक रहते हैं।", limit=10,
    ))
    titles = [r.memory.title for r in results]
    assert "Completed: Solar system research" not in titles


@pytest.mark.asyncio
async def test_matching_hindi_query_still_finds_a_hindi_memory(store, retriever):
    """The fix must not make Hindi queries unable to match anything -
    genuine overlap (a Hindi memory containing the same Hindi words)
    must still surface."""
    entry = MemoryEntry(
        type=MemoryType.PREFERENCE,
        title="मेमोरी प्राथमिकता",
        content="मुझे संक्षिप्त जवाब पसंद हैं",
        summary="मुझे संक्षिप्त जवाब पसंद हैं",
        entities=[], tags=["conversation"],
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference="test")],
        importance=0.5, confidence=0.9,
    )
    await store.save(entry)

    results = await retriever.search(MemoryQuery(text="संक्षिप्त जवाब पसंद", limit=10))
    titles = [r.memory.title for r in results]
    assert "मेमोरी प्राथमिकता" in titles


@pytest.mark.asyncio
async def test_matching_english_query_still_finds_an_english_memory(store, retriever):
    """Sanity: the fix (switching [a-z0-9_]+ to \\w+) must not break
    the existing, working English-query case."""
    await _save_solar_system_memory(store)

    results = await retriever.search(MemoryQuery(text="solar system objects orbit", limit=10))
    titles = [r.memory.title for r in results]
    assert "Completed: Solar system research" in titles


@pytest.mark.asyncio
async def test_empty_query_text_still_uses_the_default_keyword_weight(store, retriever):
    """An EMPTY query.text (browse-all / filter-only search) is the one
    genuinely ambiguous case the 0.4 default is for - unlike a non-empty
    Hindi query with zero overlap, this must still return results."""
    await _save_solar_system_memory(store)

    results = await retriever.search(MemoryQuery(text="", limit=10))
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_a_translated_unrelated_english_query_still_does_not_surface_via_hash_embedding_noise(store, retriever):
    """The exact production bug's second half: even after fixing the
    Devanagari tokenization gap, a query the general planner TRANSLATED
    to English ("Gunjan's preferences and business details") still had
    zero keyword overlap with the stale Solar System memory - but the
    0.05 semantic-similarity floor was low enough that
    LocalHashEmbeddingProvider's own hash-collision noise (unrelated
    phrases score ~0.05-0.10 purely by chance in a 96-dim hashed space)
    let it through anyway. Raising the floor to 0.2 must reject this
    the same as the pure-keyword case."""
    await _save_solar_system_memory(store)

    results = await retriever.search(MemoryQuery(
        text="Gunjan's preferences and business details", limit=10,
    ))
    titles = [r.memory.title for r in results]
    assert "Completed: Solar system research" not in titles


@pytest.mark.asyncio
async def test_corpus_ubiquitous_tokens_are_excluded_from_keyword_overlap(store, retriever):
    """The production bug's third layer: a query and an unrelated
    memory can share only tokens that are UBIQUITOUS in this
    single-user store ("vyom", the user's own name) - static stopwords
    don't catch these because they're real words, not grammar. When
    most of the corpus contains the token, it must not count as
    meaningful overlap."""
    # Build a corpus where "vyom" and "gunjan" appear in most memories
    # (as they genuinely do in production), plus one truly unrelated
    # memory that ALSO happens to contain both.
    common_entries = [
        ("VYOM said hello to Gunjan", "VYOM confirmed it is working for Gunjan"),
        ("Gunjan asked VYOM about the weather", "VYOM answered Gunjan's weather question"),
        ("VYOM completed a task for Gunjan", "The task VYOM ran for Gunjan succeeded"),
        ("Gunjan and VYOM discussed the schedule", "VYOM reviewed Gunjan's calendar"),
        ("VYOM greeted Gunjan this morning", "VYOM said good morning to Gunjan"),
        ("Gunjan asked VYOM to open an app", "VYOM opened the app Gunjan wanted"),
        ("VYOM told Gunjan the time", "VYOM read the clock for Gunjan"),
        ("Gunjan thanked VYOM for the help", "VYOM acknowledged Gunjan's thanks"),
    ]
    for title, content in common_entries:
        await store.save(MemoryEntry(
            type=MemoryType.SEMANTIC, title=title, content=content, summary=content,
            entities=[], tags=["conversation"],
            provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference="test")],
            importance=0.5, confidence=0.9,
        ))
    # The genuinely unrelated memory: shares ONLY "vyom" and "gunjan"
    # with the query below, nothing else.
    await store.save(MemoryEntry(
        type=MemoryType.SEMANTIC,
        title="Completed: Send an email to gunjan@example.com about VYOM real fix",
        content="Sent an SMTP email to gunjan@example.com confirming a code deployment finished",
        summary="Sent email to gunjan@example.com about a VYOM bugfix",
        entities=[], tags=["conversation"],
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference="test")],
        importance=0.5, confidence=0.9,
    ))

    results = await retriever.search(MemoryQuery(
        text="Can VYOM save Gunjan's personal details automatically into memory?", limit=10,
    ))
    titles = [r.memory.title for r in results]
    assert not any("Send an email" in t for t in titles)
