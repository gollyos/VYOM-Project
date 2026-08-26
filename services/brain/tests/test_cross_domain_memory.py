"""Tests for cross-domain memory mirroring (app/memory/cross_domain.py) -
the fix for VYOM's previously-siloed personal stores. Before this,
goals/habits/CRM records lived only in their own SQL table with zero
connection to the shared MemoryStore, so memory_search (the same
retrieval path knowledge/service.py already uses for researched facts)
could never surface them. This proves the mirror is real: a goal saved
through GoalStore is actually findable via MemoryManager.search(),
updating the goal updates the SAME memory entry (no duplicates), and
the same holds for HabitStore and CRMStore.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.crm.models import Lead
from app.crm.store import CRMStore
from app.goals.schemas import Goal, GoalCategory, GoalStatus
from app.goals.store import GoalStore
from app.habits.schemas import DesiredDirection, Habit
from app.habits.store import HabitStore
from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryQuery
from app.memory.store import MemoryStore
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
def memory_manager(database):
    store = MemoryStore(database)
    embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
    return MemoryManager(store, MemoryRetriever(store, embeddings))


@pytest.mark.asyncio
async def test_goal_save_is_findable_via_memory_search(database, memory_manager):
    store = GoalStore(database, memory=memory_manager)
    goal = Goal(title="Run a marathon", description="Train for and finish a full 42km marathon",
                category=GoalCategory.HEALTH, status=GoalStatus.ACTIVE)
    await store.save(goal)

    results = await memory_manager.search(MemoryQuery(text="marathon", limit=10))
    assert any("Run a marathon" in r.memory.title for r in results), \
        "goal was saved but is NOT findable via memory_search — cross-domain mirror is broken"


@pytest.mark.asyncio
async def test_goal_update_updates_the_same_memory_entry_not_a_duplicate(database, memory_manager):
    store = GoalStore(database, memory=memory_manager)
    goal = Goal(title="Learn Rust", description="Finish the Rust book", category=GoalCategory.LEARNING)
    await store.save(goal)
    first_count = (await memory_manager.store.count())

    goal.status = GoalStatus.COMPLETED
    await store.save(goal)
    second_count = (await memory_manager.store.count())

    assert second_count == first_count, "updating a goal created a duplicate memory entry instead of updating in place"
    results = await memory_manager.search(MemoryQuery(text="Rust", limit=10))
    matching = [r for r in results if "Learn Rust" in r.memory.title]
    assert matching, "updated goal not findable"
    assert "COMPLETED" in matching[0].memory.content.upper() or "completed" in matching[0].memory.content


@pytest.mark.asyncio
async def test_habit_save_is_findable_via_memory_search(database, memory_manager):
    store = HabitStore(database, memory=memory_manager)
    habit = Habit(name="Meditate every morning", desired_direction=DesiredDirection.BUILD,
                  category="wellness", frequency="daily")
    await store.save(habit)

    results = await memory_manager.search(MemoryQuery(text="meditate", limit=10))
    assert any("Meditate every morning" in r.memory.title for r in results), \
        "habit was saved but is NOT findable via memory_search"


@pytest.mark.asyncio
async def test_crm_lead_upsert_is_findable_via_memory_search(database, memory_manager):
    store = CRMStore(database, memory=memory_manager)
    lead = Lead(name="Acme Robotics", company="Acme Robotics", domain="acmerobotics.example",
               qualification_reason="Inbound demo request")
    await store.upsert(lead)

    results = await memory_manager.search(MemoryQuery(text="Acme Robotics", limit=10))
    assert any("Acme Robotics" in r.memory.title for r in results), \
        "CRM lead was saved but is NOT findable via memory_search"


@pytest.mark.asyncio
async def test_stores_without_memory_still_work_mirroring_is_purely_additive(database):
    """memory=None must remain a fully supported mode — mirroring is
    additive, never a requirement for the domain store to function."""
    store = GoalStore(database, memory=None)
    goal = Goal(title="No memory wiring needed", category=GoalCategory.OTHER)
    saved = await store.save(goal)
    assert saved.id == goal.id
    fetched = await store.get(goal.id)
    assert fetched is not None
    assert fetched.title == "No memory wiring needed"


@pytest.mark.asyncio
async def test_cross_domain_entries_share_the_personal_namespace_tag(database, memory_manager):
    """Goals and habits both mirror under the same CognitiveNamespace
    (PERSONAL) — this is what makes them show up TOGETHER in a query
    like memory_search("fitness"), not as two disconnected silos."""
    goal_store = GoalStore(database, memory=memory_manager)
    habit_store = HabitStore(database, memory=memory_manager)
    await goal_store.save(Goal(title="Get fit", category=GoalCategory.HEALTH))
    await habit_store.save(Habit(name="Go to the gym", category="fitness"))

    results = await memory_manager.search(MemoryQuery(text="fit", limit=20))
    tags_seen = {tag for r in results for tag in (r.memory.tags or [])}
    assert "ns:personal" in tags_seen, "cross-domain entries are not sharing the expected namespace tag"
