"""Integration test: MemoryManager.remember() genuinely creates
RELATED_TO relationships and re-renders the vault with [[wikilinks]]
end-to-end - not just the pure-function unit tests in
test_auto_linker.py, but the real wired-together save path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryType,
    RelationType,
)
from app.memory.store import MemoryStore
from app.memory.vault import MemoryVault
from app.migrations.manager import MigrationManager
from app.persistence.database import Database


def _memory(title: str, entities: list[str] | None = None, **overrides) -> MemoryEntry:
    defaults = dict(
        type=MemoryType.SEMANTIC,
        title=title,
        content=title,
        summary=title,
        entities=entities or [],
        provenance=[MemoryProvenance(type="user_statement", reference="test")],
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    await MigrationManager(db).apply_pending()
    yield db
    await db.close()


@pytest.fixture
def manager(database, tmp_path: Path):
    vault = MemoryVault(tmp_path / "vault")
    store = MemoryStore(database, vault=vault)
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    retriever = MemoryRetriever(store, embeddings)
    return MemoryManager(store, retriever)


@pytest.mark.asyncio
async def test_remembering_a_related_memory_creates_a_real_relationship(manager):
    a = await manager.remember(_memory("Luxora Designs project kickoff", entities=["Luxora Designs"]))
    b = await manager.remember(_memory("Luxora Designs invoice sent", entities=["Luxora Designs"]))

    relationships = await manager.store.relationships(b.id, relation=RelationType.RELATED_TO.value)
    assert len(relationships) >= 1
    linked_ids = {rel.source_id for rel in relationships} | {rel.target_id for rel in relationships}
    assert a.id in linked_ids


@pytest.mark.asyncio
async def test_remembering_a_related_memory_writes_a_wikilink_to_disk(manager):
    a = await manager.remember(_memory("Luxora Designs project kickoff", entities=["Luxora Designs"]))
    b = await manager.remember(_memory("Luxora Designs invoice sent", entities=["Luxora Designs"]))

    path_b = manager.store.vault.path_for(b)
    text_b = path_b.read_text(encoding="utf-8")
    assert "## Related" in text_b
    assert a.id in text_b

    # Backlink: the FIRST memory's file must also be re-rendered with a
    # link back to the second, not just a one-directional mention.
    path_a = manager.store.vault.path_for(a)
    text_a = path_a.read_text(encoding="utf-8")
    assert "## Related" in text_a
    assert b.id in text_a


@pytest.mark.asyncio
async def test_unrelated_memories_get_no_relationship(manager):
    await manager.remember(_memory("Luxora Designs project kickoff", entities=["Luxora Designs"]))
    weather = await manager.remember(_memory("Weather forecast for tomorrow"))

    relationships = await manager.store.relationships(weather.id, relation=RelationType.RELATED_TO.value)
    assert relationships == []


@pytest.mark.asyncio
async def test_auto_link_failure_never_breaks_the_save(manager, monkeypatch):
    """Best-effort by design: even if relationship creation itself
    raises (e.g. a transient DB error), remember() must still return
    the successfully-saved memory - the auto-linker's internal
    try/except must swallow it, not blow up an already-successful
    save."""
    await manager.remember(_memory("Luxora Designs project kickoff", entities=["Luxora Designs"]))

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated relationship-store failure")

    monkeypatch.setattr(manager.relationships, "connect", _boom)
    saved = await manager.remember(_memory("Luxora Designs invoice sent", entities=["Luxora Designs"]))
    assert saved.id is not None
