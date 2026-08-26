"""Tests for KnowledgeStore.search_subjects' stopword filtering
(app/knowledge/store.py) - a real production bug: a query like
"Gunjan's preferences and business details" LIKE-matched ANY subject
merely containing "and" as a substring (a stored subject like
"formation and evolution of the Solar System"), surfacing completely
unrelated facts for a personal-memory question that had zero real
subject-matter overlap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.schemas import KnowledgeFact, utc_now
from app.knowledge.store import KnowledgeStore
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
def store(database):
    return KnowledgeStore(database)


async def _record_solar_system_fact(store: KnowledgeStore) -> None:
    fact = KnowledgeFact(
        subject="The first step toward a theory of Solar System formation and evolution",
        predicate="is a",
        value="general acceptance of heliocentrism",
        domain="general",
        source_url="https://en.wikipedia.org/wiki/Formation_and_evolution_of_the_Solar_System",
        source_title="Formation and evolution of the Solar System - Wikipedia",
        confidence=0.55,
    )
    await store.save(fact)


@pytest.mark.asyncio
async def test_unrelated_query_sharing_only_a_stopword_does_not_match_a_subject(store):
    """The exact production bug: a query whose only lexical overlap
    with a stored subject is the stopword "and" must not resolve to
    that subject via the substring-match fallback."""
    await _record_solar_system_fact(store)

    resolved = await store.search_subjects("Gunjan's preferences and business details")
    assert resolved == []


@pytest.mark.asyncio
async def test_genuine_overlap_still_resolves_the_subject(store):
    """The stopword filter must not break real substring matching -
    "solar system" genuinely shares content words with the stored
    subject and should still resolve it."""
    await _record_solar_system_fact(store)

    resolved = await store.search_subjects("solar system formation")
    assert len(resolved) >= 1
