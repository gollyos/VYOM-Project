"""Tests for VYOM's agent-to-agent messaging (app/kanban/store.py
AgentMessageStore) - the single-Brain scoped equivalent of Hermes's
own tools/bot_relay.py message_agent, letting one kanban worker leave
a message for another to read. Real Database, no mocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.kanban.store import AgentMessageStore
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
    return AgentMessageStore(database)


@pytest.mark.asyncio
async def test_send_and_receive_a_message(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="I finished the research")
    inbox = await store.inbox("card_b")
    assert len(inbox) == 1
    assert inbox[0]["content"] == "I finished the research"
    assert inbox[0]["from_card_id"] == "card_a"


@pytest.mark.asyncio
async def test_inbox_only_returns_undelivered_by_default(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="msg1")
    first_read = await store.inbox("card_b")
    assert len(first_read) == 1
    second_read = await store.inbox("card_b")
    assert len(second_read) == 0  # already delivered, not returned again


@pytest.mark.asyncio
async def test_mark_delivered_false_peeks_without_consuming(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="peek me")
    peek1 = await store.inbox("card_b", mark_delivered=False)
    peek2 = await store.inbox("card_b", mark_delivered=False)
    assert len(peek1) == 1
    assert len(peek2) == 1  # still undelivered, both peeks see it


@pytest.mark.asyncio
async def test_inbox_is_scoped_to_the_correct_recipient(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="for b")
    await store.send(from_card_id="card_a", to_card_id="card_c", content="for c")
    inbox_b = await store.inbox("card_b")
    inbox_c = await store.inbox("card_c")
    assert [m["content"] for m in inbox_b] == ["for b"]
    assert [m["content"] for m in inbox_c] == ["for c"]


@pytest.mark.asyncio
async def test_history_includes_sent_and_received_even_after_delivery(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="hello")
    await store.inbox("card_b")  # mark delivered
    history_a = await store.history("card_a")
    history_b = await store.history("card_b")
    assert len(history_a) == 1  # card_a sent it
    assert len(history_b) == 1  # card_b received it
    assert history_b[0]["delivered"] == 1


@pytest.mark.asyncio
async def test_messages_arrive_in_order(store):
    await store.send(from_card_id="card_a", to_card_id="card_b", content="first")
    await store.send(from_card_id="card_a", to_card_id="card_b", content="second")
    inbox = await store.inbox("card_b")
    assert [m["content"] for m in inbox] == ["first", "second"]


@pytest.mark.asyncio
async def test_empty_inbox_for_a_card_with_no_messages(store):
    inbox = await store.inbox("nobody-sent-anything")
    assert inbox == []
