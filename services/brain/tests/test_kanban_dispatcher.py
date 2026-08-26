"""Tests for VYOM's Kanban dispatcher (app/kanban/dispatcher.py) - the
piece that claims PENDING cards and spawns a real OS subprocess per
card. Uses a real Database + KanbanStore; the subprocess itself is a
tiny throwaway Python script (not the real worker.py, which needs a
live Brain HTTP server) so these tests exercise genuine process
spawning without needing a running server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.kanban.dispatcher import KanbanDispatcher
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
async def test_dispatch_one_claims_and_spawns_a_real_process(store, monkeypatch):
    await store.create(title="card1", goal="do it")
    dispatcher = KanbanDispatcher(store)

    import subprocess as subprocess_module
    original_popen = subprocess_module.Popen

    def fake_popen(args, **kwargs):
        # Replace the module invocation with a trivial script so no live
        # Brain server is required, while still spawning a REAL process.
        return original_popen([sys.executable, "-c", "pass"])

    monkeypatch.setattr(subprocess_module, "Popen", fake_popen)

    card = await dispatcher._dispatch_one_if_capacity()
    assert card is not None
    assert dispatcher.active_worker_count() == 1

    in_progress = await store.get(card.id)
    assert in_progress.status == KanbanStatus.IN_PROGRESS
    assert in_progress.worker_pid is not None and in_progress.worker_pid > 0


@pytest.mark.asyncio
async def test_dispatch_respects_max_concurrent_workers(store, monkeypatch):
    for i in range(5):
        await store.create(title=f"card{i}", goal="x")
    dispatcher = KanbanDispatcher(store, max_concurrent_workers=2)

    import subprocess as subprocess_module
    original_popen = subprocess_module.Popen
    monkeypatch.setattr(subprocess_module, "Popen", lambda args, **kwargs: original_popen([sys.executable, "-c", "pass"]))

    await dispatcher._dispatch_one_if_capacity()
    await dispatcher._dispatch_one_if_capacity()
    third = await dispatcher._dispatch_one_if_capacity()

    assert third is None  # at capacity, third claim must be refused
    assert dispatcher.active_worker_count() == 2
    # The two claimed cards must be IN_PROGRESS; the rest still PENDING.
    pending = await store.list(status=KanbanStatus.PENDING)
    assert len(pending) == 3


@pytest.mark.asyncio
async def test_dispatch_one_returns_none_when_nothing_pending(store):
    dispatcher = KanbanDispatcher(store)
    result = await dispatcher._dispatch_one_if_capacity()
    assert result is None


@pytest.mark.asyncio
async def test_reap_finished_clears_completed_processes(store, monkeypatch):
    await store.create(title="quick", goal="x")
    dispatcher = KanbanDispatcher(store)

    import subprocess as subprocess_module
    original_popen = subprocess_module.Popen
    monkeypatch.setattr(subprocess_module, "Popen", lambda args, **kwargs: original_popen([sys.executable, "-c", "pass"]))

    await dispatcher._dispatch_one_if_capacity()
    assert dispatcher.active_worker_count() == 1

    # Give the trivial `python -c "pass"` process a moment to exit.
    import asyncio
    for _ in range(50):
        await asyncio.sleep(0.1)
        await dispatcher._reap_finished()
        if dispatcher.active_worker_count() == 0:
            break
    assert dispatcher.active_worker_count() == 0


@pytest.mark.asyncio
async def test_start_and_stop_do_not_raise(store):
    """The dispatch loop must be safely startable/stoppable without
    hanging, same invariant as AutomationScheduler and Curator."""
    dispatcher = KanbanDispatcher(store, poll_seconds=1)
    dispatcher.start()
    await dispatcher.stop()


def test_default_max_concurrent_workers_matches_hermes_batch_default(store):
    """Hermes's own delegate_task defaults to up to 10 parallel
    children per batch - VYOM's dispatcher default is set the same
    way, a deliberate parity choice."""
    dispatcher = KanbanDispatcher(store)
    assert dispatcher.max_concurrent_workers == 10


@pytest.mark.asyncio
async def test_worker_spawn_never_shows_a_visible_console_window(store, monkeypatch):
    """A kanban worker is background execution, same invariant VYOM's
    own terminal.py already applies to every tool-invoked command -
    the user should never see a console window flash on screen per
    claimed card. Captures the REAL kwargs Popen is called with,
    unlike the other dispatch tests whose fake_popen ignores kwargs
    entirely (which is why this regression wasn't caught earlier)."""
    await store.create(title="silent", goal="x")
    dispatcher = KanbanDispatcher(store)

    import subprocess as subprocess_module
    captured_kwargs: dict = {}
    original_popen = subprocess_module.Popen

    def fake_popen(args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_popen([sys.executable, "-c", "pass"])

    monkeypatch.setattr(subprocess_module, "Popen", fake_popen)
    await dispatcher._dispatch_one_if_capacity()

    assert captured_kwargs.get("creationflags") == getattr(subprocess_module, "CREATE_NO_WINDOW", 0x0800_0000)
    assert captured_kwargs.get("stdout") == subprocess_module.DEVNULL
    assert captured_kwargs.get("stderr") == subprocess_module.DEVNULL
