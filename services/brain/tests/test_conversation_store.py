"""Tests for the raw turn-by-turn conversation transcript
(app/persistence/conversation_store.py) - the fix for VYOM having no
equivalent to Hermes's own messages table (13,903 real rows, FTS5
searchable). Real Database + ConversationStore, no mocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.migrations.manager import MigrationManager
from app.persistence.conversation_store import ConversationStore, ConversationTurn
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
    return ConversationStore(database)


@pytest.mark.asyncio
async def test_record_exchange_writes_both_turns(store):
    turns = await store.record_exchange(
        context_id="desktop:primary", task_id="task_abc",
        user_message="post a hello message to discord", assistant_response="Posted to #general.",
    )
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    assert await store.count() == 2


@pytest.mark.asyncio
async def test_history_returns_oldest_first_for_one_context(store):
    await store.record_exchange(context_id="ctx-a", task_id="t1", user_message="first", assistant_response="ok")
    await store.record_exchange(context_id="ctx-a", task_id="t2", user_message="second", assistant_response="ok2")
    await store.record_exchange(context_id="ctx-b", task_id="t3", user_message="other context", assistant_response="ok3")

    history = await store.history("ctx-a")
    assert [t.content for t in history] == ["first", "ok", "second", "ok2"]
    assert all(t.context_id == "ctx-a" for t in history)


@pytest.mark.asyncio
async def test_search_finds_real_content_via_fts(store):
    await store.record_exchange(
        context_id="desktop:primary", task_id="t1",
        user_message="what is the marathon training plan", assistant_response="Run 5k three times a week.",
    )
    await store.record_exchange(
        context_id="desktop:primary", task_id="t2",
        user_message="send an email to the client", assistant_response="Sent.",
    )

    results = await store.search("marathon")
    assert len(results) >= 1
    assert any("marathon" in r.content for r in results)
    # unrelated query should not match
    assert not any("marathon" in r.content for r in await store.search("email"))


@pytest.mark.asyncio
async def test_search_can_be_scoped_to_one_context(store):
    await store.record_exchange(context_id="ctx-a", task_id="t1", user_message="unique-marker-alpha", assistant_response="ok")
    await store.record_exchange(context_id="ctx-b", task_id="t2", user_message="unique-marker-alpha", assistant_response="ok")

    scoped = await store.search("unique-marker-alpha", context_id="ctx-a")
    assert all(t.context_id == "ctx-a" for t in scoped)
    assert len(scoped) == 1

    unscoped = await store.search("unique-marker-alpha")
    assert len(unscoped) == 2


@pytest.mark.asyncio
async def test_search_with_no_matching_fts_returns_empty_not_error(store):
    await store.record_exchange(context_id="ctx-a", task_id="t1", user_message="hello", assistant_response="hi")
    results = await store.search("completely-absent-token-xyz")
    assert results == []
