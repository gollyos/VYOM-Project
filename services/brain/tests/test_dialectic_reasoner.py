"""Tests for the dialectic reasoning pass (app/adaptive/dialectic_reasoner.py)
- the Honcho-style upgrade that derives NEW facts from raw conversation
turns instead of only linting existing ones. Real ConversationStore +
KnowledgeService, no mocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adaptive.dialectic_reasoner import DialecticReasoner
from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore
from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.store import MemoryStore
from app.migrations.manager import MigrationManager
from app.persistence.conversation_store import ConversationStore
from app.persistence.database import Database


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    await MigrationManager(db).apply_pending()
    yield db
    await db.close()


@pytest.fixture
def conversation_store(database):
    return ConversationStore(database)


@pytest.fixture
def knowledge_service(database):
    store = MemoryStore(database)
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    memory = MemoryManager(store, MemoryRetriever(store, embeddings))
    return KnowledgeService(KnowledgeStore(database), memory)


@pytest.fixture
def reasoner(conversation_store, knowledge_service):
    return DialecticReasoner(conversation_store, knowledge_service)


@pytest.mark.asyncio
async def test_extracts_a_stated_preference(conversation_store, knowledge_service, reasoner):
    await conversation_store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="I prefer dark mode for all my apps", assistant_response="Noted.",
    )
    findings = await reasoner.run()
    assert any(f.predicate == "prefers" and "dark mode" in f.value for f in findings)


@pytest.mark.asyncio
async def test_extracted_preferences_are_recorded_as_knowledge_facts(conversation_store, knowledge_service, reasoner):
    await conversation_store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="I hate getting notifications after 9pm", assistant_response="Got it.",
    )
    await reasoner.run()
    facts = await knowledge_service.store.facts_in_domain("personal")
    assert any(f.predicate == "dislikes" for f in facts)


@pytest.mark.asyncio
async def test_inferred_facts_have_lower_confidence_than_explicit_ones(conversation_store, knowledge_service, reasoner):
    await conversation_store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="I always check my email before starting work", assistant_response="OK.",
    )
    findings = await reasoner.run()
    assert all(f.confidence < 1.0 for f in findings)


@pytest.mark.asyncio
async def test_recurring_topic_across_distinct_turns_is_surfaced(conversation_store, knowledge_service, reasoner):
    for i in range(3):
        await conversation_store.record_exchange(
            context_id="desktop:primary", task_id=f"t{i}",
            user_message=f"can you check the marathon training schedule number {i}", assistant_response="ok",
        )
    findings = await reasoner.run()
    assert any(f.predicate == "frequently discusses" and f.value == "marathon" for f in findings)


@pytest.mark.asyncio
async def test_repeated_word_within_one_message_does_not_count_as_recurring(conversation_store, knowledge_service, reasoner):
    """A topic must recur across DISTINCT turns, not just be repeated
    within one verbose message - otherwise one message about anything
    looks like a pattern."""
    await conversation_store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="banana banana banana banana banana", assistant_response="ok",
    )
    findings = await reasoner.run()
    assert not any(f.value == "banana" for f in findings)


@pytest.mark.asyncio
async def test_no_conversation_history_yields_no_findings(conversation_store, knowledge_service, reasoner):
    findings = await reasoner.run()
    assert findings == []


@pytest.mark.asyncio
async def test_run_is_idempotent_re_recording_does_not_duplicate(conversation_store, knowledge_service, reasoner):
    await conversation_store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="I prefer short emails", assistant_response="OK.",
    )
    await reasoner.run()
    first_count = len(await knowledge_service.store.facts_in_domain("personal"))
    await reasoner.run()
    second_count = len(await knowledge_service.store.facts_in_domain("personal"))
    assert second_count == first_count
