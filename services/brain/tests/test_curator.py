"""Tests for VYOM's Curator (app/adaptive/curator.py) - idle-triggered
background self-review mirroring Hermes's own curator.py pattern.
Real Database + stores, no mocks: a curator run genuinely calls
KnowledgeService.lint() and reads real automation rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.adaptive.curator import Curator, CuratorRunStore
from app.automation.schemas import AutomationCreate, AutomationStatus, AutomationType
from app.automation.store import AutomationStore
from app.knowledge.schemas import KnowledgeFact
from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore
from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.store import MemoryStore
from app.migrations.manager import MigrationManager
from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.schemas.tasks import Task


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "brain.db")
    await db.connect()
    await MigrationManager(db).apply_pending()
    yield db
    await db.close()


@pytest.fixture
def task_store(database):
    return TaskStore(database)


@pytest.fixture
def run_store(database):
    return CuratorRunStore(database)


@pytest.fixture
def knowledge_service(database):
    store = MemoryStore(database)
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    memory = MemoryManager(store, MemoryRetriever(store, embeddings))
    return KnowledgeService(KnowledgeStore(database), memory)


@pytest.fixture
def automation_store(database):
    return AutomationStore(database)


@pytest.mark.asyncio
async def test_run_once_records_a_curator_run(task_store, run_store):
    curator = Curator(task_store=task_store, run_store=run_store)
    summary = await curator.run_once()
    assert "run_id" in summary
    runs = await run_store.recent()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_run_once_surfaces_real_contradicted_facts(task_store, run_store, knowledge_service):
    await knowledge_service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Guido van Rossum", domain="research"))
    await knowledge_service.record_fact(KnowledgeFact(
        subject="Python", predicate="created by", value="Someone Else", domain="research"))

    curator = Curator(task_store=task_store, run_store=run_store, knowledge_service=knowledge_service)
    summary = await curator.run_once()

    assert summary["knowledge_lint"] is not None
    assert summary["knowledge_lint"]["totals"]["contradicted"] >= 1


@pytest.mark.asyncio
async def test_run_once_surfaces_paused_automations(task_store, run_store, automation_store):
    automation = AutomationCreate(name="test-automation", type=AutomationType.RECURRING,
                                  action="do something", interval_minutes=60)
    from app.automation.schemas import Automation
    saved = Automation.from_create(automation)
    saved.status = AutomationStatus.PAUSED
    await automation_store.save(saved)

    curator = Curator(task_store=task_store, run_store=run_store, automation_store=automation_store)
    summary = await curator.run_once()

    assert len(summary["stale_automations"]) == 1
    assert summary["stale_automations"][0]["name"] == "test-automation"


@pytest.mark.asyncio
async def test_should_run_is_false_immediately_after_a_run(task_store, run_store):
    curator = Curator(task_store=task_store, run_store=run_store, interval_hours=24)
    assert await curator._should_run() is True
    await curator.run_once()
    assert await curator._should_run() is False


@pytest.mark.asyncio
async def test_should_run_is_false_when_a_task_completed_recently(task_store, run_store):
    task = Task(goal="do something", user_request="do something")
    task.completed_at = datetime.now(timezone.utc)
    await task_store.save(task)

    curator = Curator(task_store=task_store, run_store=run_store, min_idle_minutes=30)
    assert await curator._should_run() is False


@pytest.mark.asyncio
async def test_should_run_is_true_when_idle_long_enough(task_store, run_store):
    task = Task(goal="do something", user_request="do something")
    task.completed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await task_store.save(task)

    curator = Curator(task_store=task_store, run_store=run_store, min_idle_minutes=30)
    assert await curator._should_run() is True


@pytest.mark.asyncio
async def test_start_and_stop_do_not_raise(task_store, run_store):
    """The idle loop must be safely startable/stoppable without ever
    blocking process shutdown - same invariant as AutomationScheduler."""
    curator = Curator(task_store=task_store, run_store=run_store, poll_seconds=0.05)
    curator.start()
    await curator.stop()  # must return promptly, not hang
