"""Tests for VYOM's Kanban store (app/kanban/store.py) - the multi-agent
task board mirroring Hermes's own kanban_db.py claim/complete/block
lifecycle. Real Database, no mocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.kanban.store import KanbanStatus, KanbanStore
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
    return KanbanStore(database)


@pytest.mark.asyncio
async def test_create_card_starts_pending(store):
    card = await store.create(title="Test card", goal="do the thing")
    assert card.status == KanbanStatus.PENDING
    fetched = await store.get(card.id)
    assert fetched is not None
    assert fetched.title == "Test card"


@pytest.mark.asyncio
async def test_claim_next_returns_oldest_pending_and_marks_claimed(store):
    first = await store.create(title="first", goal="a")
    await store.create(title="second", goal="b")

    claimed = await store.claim_next(worker_pid=1234)
    assert claimed.id == first.id
    assert claimed.status == KanbanStatus.CLAIMED
    assert claimed.worker_pid == 1234
    assert claimed.claimed_at is not None


@pytest.mark.asyncio
async def test_claim_next_returns_none_when_nothing_pending(store):
    assert await store.claim_next(worker_pid=1) is None


@pytest.mark.asyncio
async def test_claim_next_never_double_claims_the_same_card(store):
    """Two concurrent dispatcher ticks racing claim_next must never both
    win the same card - the single-writer UPDATE...WHERE status=PENDING
    guard is what prevents it."""
    await store.create(title="race", goal="a")

    import asyncio
    results = await asyncio.gather(
        store.claim_next(worker_pid=1), store.claim_next(worker_pid=2),
    )
    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1


@pytest.mark.asyncio
async def test_full_lifecycle_claim_to_complete(store):
    card = await store.create(title="lifecycle", goal="do it")
    claimed = await store.claim_next(worker_pid=99)
    await store.mark_in_progress(claimed.id)
    in_progress = await store.get(claimed.id)
    assert in_progress.status == KanbanStatus.IN_PROGRESS

    await store.complete(claimed.id, result={"response": "done"})
    completed = await store.get(claimed.id)
    assert completed.status == KanbanStatus.COMPLETED
    assert completed.result == {"response": "done"}
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_fail_records_error(store):
    card = await store.create(title="will fail", goal="x")
    await store.fail(card.id, error="something broke")
    failed = await store.get(card.id)
    assert failed.status == KanbanStatus.FAILED
    assert failed.error == "something broke"


@pytest.mark.asyncio
async def test_block_records_reason(store):
    card = await store.create(title="blocked", goal="x")
    await store.block(card.id, reason="waiting on approval")
    blocked = await store.get(card.id)
    assert blocked.status == KanbanStatus.BLOCKED
    assert blocked.error == "waiting on approval"


@pytest.mark.asyncio
async def test_list_filters_by_status(store):
    a = await store.create(title="a", goal="x")
    b = await store.create(title="b", goal="y")
    await store.complete(b.id, result={})

    pending = await store.list(status=KanbanStatus.PENDING)
    completed = await store.list(status=KanbanStatus.COMPLETED)
    assert [c.id for c in pending] == [a.id]
    assert [c.id for c in completed] == [b.id]


@pytest.mark.asyncio
async def test_reclaim_stale_reclaims_a_card_whose_worker_is_dead(store):
    """A worker pid that no longer exists must be reclaimed back to
    PENDING - the crash-recovery invariant, same as
    TaskRuntime.resume_incomplete_tasks for regular tasks."""
    card = await store.create(title="crashed", goal="x")
    claimed = await store.claim_next(worker_pid=999_999_999)  # near-guaranteed not a real live pid
    await store.mark_in_progress(claimed.id)

    reclaimed_ids = await store.reclaim_stale()
    assert claimed.id in reclaimed_ids
    reclaimed_card = await store.get(claimed.id)
    assert reclaimed_card.status == KanbanStatus.PENDING
    assert reclaimed_card.worker_pid is None


@pytest.mark.asyncio
async def test_reclaim_stale_does_not_touch_a_card_with_a_live_worker(store):
    import os

    card = await store.create(title="alive", goal="x")
    claimed = await store.claim_next(worker_pid=os.getpid())  # this test process is genuinely alive
    await store.mark_in_progress(claimed.id)

    reclaimed_ids = await store.reclaim_stale()
    assert claimed.id not in reclaimed_ids
    still_in_progress = await store.get(claimed.id)
    assert still_in_progress.status == KanbanStatus.IN_PROGRESS
