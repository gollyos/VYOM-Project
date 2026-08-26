"""Boss-mode round: favourite-music recall, Boss persona, Telegram gateway.

All three ship with ZERO new paid API keys: preference memory rides the
existing store, the persona is a system-instruction change, and Telegram
uses a free BotFather token (gateway dormant until the token exists).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


async def test_favourite_statement_uses_real_conversation_capture_path(stack):
    from unittest.mock import AsyncMock

    from app.schemas.tasks import Task, TaskCreate

    stack.task_store = SimpleNamespace(save=AsyncMock())
    stack._emit = AsyncMock()
    statement = Task.from_create(
        TaskCreate(user_request="VYOM mujhe Danda Noli gaana pasand hai"))
    stored = await stack._capture_conversational_facts(statement)
    assert stored == ["Boss favourite music: Danda Noli"]

    play = Task.from_create(TaskCreate(user_request="Boss mera favourite song chala do"))
    assert await stack._media_preference_query(play) == "Danda Noli"
    assert play.metadata["preference_recalled"] == "Danda Noli"


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

    gateway = TelegramGateway(
        "test-token", None, None, tmp_path / "tg.json", allowed_chat_ids={"12345"})
    assert gateway._poll_task is None  # dormant until start()

    # State persists chat pairing across restarts.
    gateway._chat_ids.update({"12345", "untrusted-stale-chat"})
    gateway._offset = 77
    gateway._save_state()
    revived = TelegramGateway(
        "test-token", None, None, tmp_path / "tg.json", allowed_chat_ids={"12345"})
    assert revived._chat_ids == {"12345"} and revived._offset == 77


async def test_telegram_gateway_refuses_start_without_owner_allowlist(tmp_path):
    from app.gateway.telegram import TelegramGateway

    gateway = TelegramGateway("test-token", None, None, tmp_path / "tg.json")
    with pytest.raises(RuntimeError, match="owner chat allowlist"):
        await gateway.start()


async def test_only_allowlisted_telegram_chat_can_pair(tmp_path):
    from app.gateway.telegram import TelegramGateway

    sent: list[tuple[str, str]] = []
    gateway = TelegramGateway(
        "test-token", None, None, tmp_path / "tg.json", allowed_chat_ids={"12345"})

    async def capture(chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    gateway._send_text = capture
    await gateway._handle_message({"chat": {"id": "99999", "type": "private"}, "text": "/start"})
    assert gateway._chat_ids == set()
    assert "not authorized" in sent[-1][1]
    await gateway._handle_message({"chat": {"id": "12345", "type": "group"}, "text": "/start"})
    assert gateway._chat_ids == set()
    assert "private owner chat" in sent[-1][1]


    await gateway._handle_message({"chat": {"id": "12345", "type": "private"}, "text": "open Chrome"})
    assert "not paired" in sent[-1][1]
    await gateway._handle_message({"chat": {"id": "12345", "type": "private"}, "text": "/start"})
    assert gateway._chat_ids == {"12345"}



async def test_ten_telegram_commands_dispatch_concurrently(tmp_path):
    import asyncio

    from app.gateway.telegram import TelegramGateway

    gate = asyncio.Event()
    calls: list[tuple[str, str, str]] = []
    gateway = TelegramGateway(
        "test-token", None, None, tmp_path / "tg.json", allowed_chat_ids={"12345"})
    gateway._chat_ids.add("12345")

    async def run(chat_id: str, text: str, correlation_id: str) -> None:
        calls.append((chat_id, text, correlation_id))
        await gate.wait()

    gateway._run_command = run
    for index in range(10):
        gateway._offset = index
        await gateway._handle_message({
            "chat": {"id": "12345", "type": "private"},
            "text": f"task {index}",
        })
    await asyncio.sleep(0)

    assert len(gateway._message_tasks) == 10
    assert [(chat_id, text) for chat_id, text, _ in calls] == [
        ("12345", f"task {index}") for index in range(10)
    ]
    assert len({correlation_id for _, _, correlation_id in calls}) == 10
    gate.set()
    await asyncio.gather(*tuple(gateway._message_tasks))


async def test_telegram_command_keeps_remote_provenance_and_typed_result(tmp_path, monkeypatch):
    from app.gateway.telegram import TelegramGateway
    from app.schemas.tasks import TaskStatus

    captured = {}
    task = SimpleNamespace(id="task_telegram")
    completed = SimpleNamespace(
        status=TaskStatus.COMPLETED,
        result=SimpleNamespace(response="Chrome opened and verified."),
    )

    class Runtime:
        async def create_task(self, payload):
            captured["payload"] = payload
            return task

    class Store:
        async def get(self, _task_id):
            return completed

    async def no_sleep(_delay):
        return None

    sent: list[str] = []
    gateway = TelegramGateway(
        "test-token", Runtime(), Store(), tmp_path / "tg.json",
        allowed_chat_ids={"12345"},
    )

    async def capture(_chat_id: str, text: str) -> None:
        sent.append(text)

    gateway._send_text = capture
    monkeypatch.setattr("app.gateway.telegram.asyncio.sleep", no_sleep)
    await gateway._run_command("12345", "Chrome kholo")

    payload = captured["payload"]
    assert payload.source == "telegram:12345"
    assert payload.context_id == "telegram:12345"
    assert payload.correlation_id.startswith("telegram:12345:")
    assert payload.correlation_id != "telegram:12345:0"
    assert "Chrome opened and verified." in sent[-1]


async def test_telegram_file_export_is_restricted_to_allowed_roots(tmp_path):
    from app.gateway.telegram import TelegramGateway

    allowed = tmp_path / "artifacts"
    allowed.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("secret", encoding="utf-8")
    sent: list[str] = []
    gateway = TelegramGateway(
        "test-token", None, None, tmp_path / "tg.json",
        allowed_chat_ids={"12345"}, allowed_file_roots=[allowed],
    )

    async def capture(_chat_id: str, text: str) -> None:
        sent.append(text)

    gateway._send_text = capture
    await gateway._handle_file("12345", str(outside))
    assert "Security" in sent[-1]
