"""Repair C — permanent memory: nothing is ever erased, every edit keeps
its prior state, retrieval finds decade-old records instantly, and the
Obsidian vault mirrors it all in human-readable markdown.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryQuery,
    MemoryType,
    Sensitivity,
)
from app.memory.store import MemoryStore
from app.memory.vault import MemoryVault
from app.persistence.database import Database


def _memory(title: str = "Test memory", content: str = "Some content", **overrides):
    defaults = dict(
        type=MemoryType.SEMANTIC,
        title=title,
        content=content,
        summary=content[:50],
        provenance=[MemoryProvenance(type="user_statement", reference="test")],
        created_at=datetime(2016, 8, 22, tzinfo=timezone.utc),  # a "ten-year-old" record
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def store(database):
    return MemoryStore(database)


# -- C1: no hard delete, version history -----------------------------------


async def test_forget_is_a_tombstone_not_an_erasure(store):
    memory = await store.save(_memory(content="The WiFi password is hunter2"))
    assert await store.forget(memory.id) is True
    # Normal retrieval skips it...
    visible = await store.list()
    assert all(item.id != memory.id for item in visible)
    # ...but the row is alive a decade later, content intact.
    recovered = await store.get(memory.id, touch=False)
    assert recovered is not None and recovered.content == "The WiFi password is hunter2"
    assert recovered.deleted_at is not None
    # And the explicit history view sees it too.
    with_deleted = await store.list(include_deleted=True)
    assert any(item.id == memory.id for item in with_deleted)


async def test_double_forget_is_honest(store):
    memory = await store.save(_memory())
    assert await store.forget(memory.id) is True
    assert await store.forget(memory.id) is False


async def test_update_snapshots_the_previous_version(store):
    memory = await store.save(_memory(title="Project status", content="Phase 1 started"))
    memory.content = "Phase 3 complete"
    await store.save(memory)
    fresh = await store.get(memory.id, touch=False)
    assert fresh.version == 2
    history = await store.history(memory.id)
    assert len(history) == 1
    assert history[0].content == "Phase 1 started"
    assert history[0].version == 1


async def test_access_touches_do_not_pollute_history(store):
    memory = await store.save(_memory())
    await store.get(memory.id, touch=True)
    await store.get(memory.id, touch=True)
    assert await store.history(memory.id) == []
    fresh = await store.get(memory.id, touch=False)
    assert fresh.version == 1


# -- C2: Obsidian markdown vault -------------------------------------------


async def test_vault_mirrors_every_save_as_markdown(tmp_path: Path, database):
    vault = MemoryVault(tmp_path / "vault")
    store = MemoryStore(database, vault=vault)
    memory = await store.save(_memory(title="Luxora client preference",
                                      content="Prefers WhatsApp over email"))
    path = vault.path_for(memory)
    assert path is not None and path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "id: " + memory.id in text
    assert "Prefers WhatsApp over email" in text
    assert "Provenance" in text
    assert path.parent.parent.name == "Source"  # semantic -> Source layer


async def test_highly_sensitive_memories_never_reach_plaintext(tmp_path: Path, database):
    vault = MemoryVault(tmp_path / "vault")
    store = MemoryStore(database, vault=vault)
    memory = await store.save(_memory(title="secret thing", sensitivity=Sensitivity.HIGHLY_SENSITIVE))
    assert vault.path_for(memory) is None or not vault.path_for(memory).exists()


# -- C2b: auto-linked knowledge graph (Obsidian [[wikilinks]]) --------------


async def test_vault_renders_related_memories_as_wikilinks(tmp_path: Path, database):
    """The user's 'khudki Wikipedia jaisa Obsidian, cross-linked' request:
    a memory with a real relationship must render an Obsidian-standard
    [[stem|Title]] wikilink, not just sit as an isolated file."""
    vault = MemoryVault(tmp_path / "vault")
    store = MemoryStore(database, vault=vault)
    a = await store.save(_memory(title="Luxora Designs project kickoff"))
    b = await store.save(_memory(title="Luxora Designs invoice sent"))

    vault.write(a, related=[b])
    text = vault.path_for(a).read_text(encoding="utf-8")
    assert "## Related" in text
    assert "[[" in text and "]]" in text
    assert b.id in text  # the wikilink target embeds the real memory id


async def test_vault_omits_related_section_when_nothing_is_linked(tmp_path: Path, database):
    vault = MemoryVault(tmp_path / "vault")
    store = MemoryStore(database, vault=vault)
    memory = await store.save(_memory(title="Isolated note"))
    vault.write(memory)
    text = vault.path_for(memory).read_text(encoding="utf-8")
    assert "## Related" not in text


# -- C3: FTS + instant retrieval at scale -----------------------------------


async def test_fts_finds_a_decade_old_record_under_600_newer_rows(store):
    old = await store.save(_memory(
        title="Halol mandi vegetable rates",
        content="August 2016: tomatoes at 40 rupees per kilo in Halol mandi",
    ))
    for index in range(600):
        await store.save(_memory(
            title=f"Daily note {index}",
            content=f"Routine day {index}: emails, standup, deployment",
            created_at=datetime(2020 + index // 300, 1, 1, tzinfo=timezone.utc),
        ))
    # The structured window (newest 500) cannot reach the 2016 row.
    window = await store.list()
    assert all(item.id != old.id for item in window)
    # FTS reaches it instantly.
    hits = await store.search_fts("Halol mandi tomatoes")
    assert old.id in hits
    # And the retriever surfaces it end-to-end.
    retriever = MemoryRetriever(store, LocalHashEmbeddingProvider())
    results = await retriever.search(MemoryQuery(text="halol mandi tomato rate"))
    assert any(result.memory.id == old.id for result in results)


async def test_fts_tolerates_arbitrary_user_text(store):
    await store.save(_memory(title="Quotes", content='He said "hello"; then left.'))
    # Quotes and punctuation must not break the FTS query language.
    assert await store.search_fts('"hello"; DROP TABLE memories; --') is not None


async def test_relationship_counts_is_one_query_not_n_plus_one(store):
    first = await store.save(_memory(title="A"))
    second = await store.save(_memory(title="B"))
    counts = await store.relationship_counts([first.id, second.id])
    assert counts == {}  # no relationships yet, single query, no raise


# -- Cached embeddings ------------------------------------------------------


async def test_embedding_cache_hits_database_not_provider(database):
    calls = {"count": 0}

    class Counting(LocalHashEmbeddingProvider):
        async def embed(self, text):
            calls["count"] += 1
            return await super().embed(text)

    counting = Counting()
    cached = CachedEmbeddingProvider(database, counting)
    memory = _memory(title="cache me", content="stable content")
    haystack = "cache me stable content"
    first = await cached.embed_memory(memory, haystack)
    second = await cached.embed_memory(memory, haystack)
    assert first == second
    assert calls["count"] == 1  # second call served from the cache
    # Changed content re-embeds.
    await cached.embed_memory(memory, "cache me changed content")
    assert calls["count"] == 2
