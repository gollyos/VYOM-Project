"""Boss-mode round: favourite-music recall, Boss persona, Telegram gateway.

All three ship with ZERO new paid API keys: preference memory rides the
existing store, the persona is a system-instruction change, and Telegram
uses a free BotFather token (gateway dormant until the token exists).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.embeddings import LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryType
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.runtime.task_runtime import TaskRuntime


def _pref(content: str) -> MemoryEntry:
    return MemoryEntry(
        type=MemoryType.PREFERENCE,
        title=f"Boss ka favourite music: {content}",
        content=content,
        summary=f"Favourite song/artist: {content}",
        entities=["music"],
        provenance=[MemoryProvenance(type="user_statement", reference="voice")],
    )


@pytest.fixture
async def stack(tmp_path: Path):
    database = Database(tmp_path / "brain.db")
    await database.connect()
    store = MemoryStore(database)
    manager = MemoryManager(store, MemoryRetriever(store, LocalHashEmbeddingProvider()))
    runtime = TaskRuntime.__new__(TaskRuntime)  # only the hooks under test
    runtime.memory_store = store
    runtime.memory_manager = manager
    runtime.memory_retriever = manager.retriever
    yield runtime
    await database.close()


async def test_favourite_statement_is_saved_not_played(stack):
    from app.schemas.tasks import Task, TaskCreate

    task = Task.from_create(TaskCreate(user_request="VYOM mujhe Danda Noli gaana pasand hai"))
    override = await stack._media_preference_query(task)
    assert override is None  # statement saved; playing happens on command
    assert task.metadata["preference_saved"] == "Danda Noli"
    hits = await stack.memory_retriever.search(
        __import__("app.memory.schemas", fromlist=["MemoryQuery"]).MemoryQuery(
            types={MemoryType.PREFERENCE}, text="favourite music"))
    assert any("Danda Noli" in item.memory.content for item in hits)


async def test_favourite_play_recall_uses_memory(stack):
    from app.memory.schemas import MemoryQuery

    await stack.memory_manager.remember(_pref("Kesariya Arijit Singh"))
    from app.schemas.tasks import Task, TaskCreate

    task = Task.from_create(TaskCreate(user_request="Boss mera favourite song chala do"))
    override = await stack._media_preference_query(task)
    assert override == "Kesariya Arijit Singh"
    assert task.metadata["preference_recalled"] == "Kesariya Arijit Singh"


async def test_named_song_still_searches_the_name(stack):
    from app.schemas.tasks import Task, TaskCreate

    task = Task.from_create(TaskCreate(user_request="channa mereya chala do"))
    assert await stack._media_preference_query(task) is None


def test_boss_persona_in_system_instruction():
    from app.runtime.executor import SYSTEM_INSTRUCTION

    assert "Boss" in SYSTEM_INSTRUCTION
    assert "NON-CODER" in SYSTEM_INSTRUCTION          # no terminal steps in answers
    assert "SHARE FEELINGS" in SYSTEM_INSTRUCTION      # feelings, briefly
    assert "Gunjan's questions" not in SYSTEM_INSTRUCTION.replace("Boss's questions", "")


def test_telegram_gateway_dormant_and_parsing(tmp_path):
    from app.gateway.telegram import TelegramGateway

    gateway = TelegramGateway("test-token", None, None, tmp_path / "tg.json")
    assert gateway._poll_task is None  # dormant until start()

    # State persists chat pairing across restarts.
    gateway._chat_ids.add("12345")
    gateway._offset = 77
    gateway._save_state()
    revived = TelegramGateway("test-token", None, None, tmp_path / "tg.json")
    assert revived._chat_ids == {"12345"} and revived._offset == 77
