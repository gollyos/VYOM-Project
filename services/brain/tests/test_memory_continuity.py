from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.memory.embeddings import DisabledEmbeddingProvider
from app.automation.cron import CronValidationError, next_cron_after
from app.automation.natural_schedule import parse_schedule_request
from app.automation.schemas import Automation, AutomationCreate, AutomationType
from app.automation.store import AutomationStore
from app.memory.history import parse_historical_memory_request
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryQuery,
    MemoryType,
    ProvenanceType,
    VerificationState,
)
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.runtime.planner import needs_fresh_evidence
from app.runtime.cognitive_runtime import CognitiveRuntime
from app.runtime.task_classifier import TaskClassifier
from app.schemas.tasks import Task, TaskCreate, TaskStatus
from tests.helpers import build_runtime, close_harness, wait_for_status


def memory_entry(
    title: str,
    content: str,
    *,
    created_at: datetime,
    memory_type: MemoryType = MemoryType.PROJECT,
) -> MemoryEntry:
    return MemoryEntry(
        type=memory_type,
        title=title,
        content=content,
        summary=content,
        created_at=created_at,
        entities=[title],
        provenance=[MemoryProvenance(
            type=ProvenanceType.USER_STATEMENT,
            reference="continuity test",
            timestamp=created_at,
        )],
        verification_state=VerificationState.VERIFIED,
    )


def test_historical_request_parses_indian_day_and_subject() -> None:
    parsed = parse_historical_memory_request(
        "Maine tumhe 20/08/2016 ko client Acme ke baare me kya bataya tha?"
    )
    assert parsed.local_date == date(2016, 8, 20)
    assert parsed.subject == "Acme"
    assert parsed.created_after == datetime(2016, 8, 19, 18, 30, tzinfo=timezone.utc)
    assert parsed.created_before == datetime(2016, 8, 20, 18, 30, tzinfo=timezone.utc)


def test_classifier_routes_historical_recall_without_a_model() -> None:
    classifier = TaskClassifier()
    for request in (
        "What did I tell you on 2016-08-20 about client Acme?",
        "Maine tumhe 20 August 2016 ko client Acme ke baare me kya bataya tha?",
        "Yaad hai maine kal project Atlas ke baare me kya bola tha?",
    ):
        profile = classifier.classify(request)
        assert profile.intent == "memory_history_recall"
        assert profile.deterministic
        assert not profile.needs


def test_application_whats_new_requires_fresh_evidence() -> None:
    assert needs_fresh_evidence("n8n me new nodes kya aaye hain?")
    assert needs_fresh_evidence("What is new in the current Power Automate release?")
    assert not needs_fresh_evidence("Create a new project file")


def test_standard_cron_is_timezone_aware_and_restart_deterministic() -> None:
    after = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    # 09:30 Asia/Calcutta is 04:00 UTC.
    assert next_cron_after("30 9 * * *", after, "Asia/Calcutta") == datetime(
        2026, 8, 20, 4, tzinfo=timezone.utc
    )
    assert next_cron_after("*/15 * * * *", after, "UTC") == datetime(
        2026, 8, 20, 0, 15, tzinfo=timezone.utc
    )


def test_recurring_automation_accepts_cron_or_interval_but_not_both() -> None:
    definition = Automation.from_create(AutomationCreate(
        name="Morning status",
        type=AutomationType.RECURRING,
        action="run_vyom_command",
        cron_expression="30 9 * * 1-5",
        condition={"command": "Show my system status"},
    ))
    assert definition.next_run_at is not None
    with pytest.raises(ValueError):
        AutomationCreate(
            name="Ambiguous",
            type=AutomationType.RECURRING,
            action="run_vyom_command",
            cron_expression="0 9 * * *",
            interval_minutes=60,
            condition={"command": "Show status"},
        )
    with pytest.raises(CronValidationError):
        next_cron_after("99 9 * * *", datetime.now(timezone.utc), "UTC")


def test_natural_and_explicit_cron_requests_preserve_the_embedded_command() -> None:
    daily = parse_schedule_request("Every weekday at 9:30 AM, show my system status")
    assert daily.cron_expression == "30 9 * * 1-5"
    assert daily.condition["command"] == "show my system status"
    explicit = parse_schedule_request("cron 0 18 * * 1-5 run open the project report")
    assert explicit.cron_expression == "0 18 * * 1-5"
    assert explicit.condition["command"] == "open the project report"
    tomorrow = parse_schedule_request(
        "Kal 5 PM baje open the client report",
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert tomorrow.type == AutomationType.ONE_TIME
    assert tomorrow.condition["command"] == "open the client report"


def test_classifier_does_not_execute_the_embedded_schedule_command_immediately() -> None:
    profile = TaskClassifier().classify("Every day at 9 AM, show my system status")
    assert profile.intent == "schedule_command"
    assert profile.deterministic
    assert "tools" not in profile.needs


@pytest.mark.asyncio
async def test_memory_filters_are_applied_before_limit(tmp_path) -> None:
    database = Database(tmp_path / "memory.db")
    await database.connect()
    store = MemoryStore(database)
    old = await store.save(memory_entry(
        "Atlas",
        "Client Atlas chose the blue launch plan.",
        created_at=datetime(2016, 8, 20, 8, tzinfo=timezone.utc),
    ))
    for index in range(6):
        await store.save(memory_entry(
            f"Recent {index}",
            f"Recent preference {index}",
            created_at=datetime(2026, 8, 20, index, tzinfo=timezone.utc),
            memory_type=MemoryType.PREFERENCE,
        ))

    # Before the SQL-side filtering fix, LIMIT 5 selected only recent
    # preferences and the old project vanished before type/date filtering.
    found = await store.list(
        types={MemoryType.PROJECT},
        created_after=datetime(2016, 8, 20, tzinfo=timezone.utc),
        created_before=datetime(2016, 8, 21, tzinfo=timezone.utc),
        limit=5,
    )
    assert [item.id for item in found] == [old.id]
    await database.close()


@pytest.mark.asyncio
async def test_history_can_show_superseded_fact_without_reviving_current_truth(tmp_path) -> None:
    database = Database(tmp_path / "memory.db")
    await database.connect()
    store = MemoryStore(database)
    retriever = MemoryRetriever(store, DisabledEmbeddingProvider())
    manager = MemoryManager(store, retriever)
    old_time = datetime(2016, 8, 20, 8, tzinfo=timezone.utc)
    old = await manager.remember(memory_entry(
        "Client Atlas status", "Atlas contact was Riya.", created_at=old_time,
        memory_type=MemoryType.CLIENT,
    ))
    replacement = memory_entry(
        "Client Atlas status", "Atlas contact is now Dev.",
        created_at=old_time + timedelta(days=1), memory_type=MemoryType.CLIENT,
    )
    await manager.correct(old.id, replacement)

    current = await manager.search(MemoryQuery(text="Atlas contact", limit=10))
    history = await manager.search(MemoryQuery(
        text="Atlas contact",
        created_after=old_time.replace(hour=0),
        created_before=old_time.replace(hour=0) + timedelta(days=1),
        include_superseded=True,
        limit=10,
    ))
    assert old.id not in {item.memory.id for item in current}
    assert old.id in {item.memory.id for item in history}
    assert (await store.get(old.id, touch=False)).verification_state == VerificationState.SUPERSEDED
    await database.close()


@pytest.mark.asyncio
async def test_task_history_searches_original_user_statement_before_limit(tmp_path) -> None:
    database = Database(tmp_path / "tasks.db")
    await database.connect()
    store = TaskStore(database)
    old = Task.from_create(TaskCreate(user_request="Client Atlas chose the blue launch plan"))
    old.created_at = datetime(2016, 8, 20, 9, tzinfo=timezone.utc)
    await store.save(old)
    for index in range(6):
        recent = Task.from_create(TaskCreate(user_request=f"Unrelated recent command {index}"))
        recent.created_at = datetime(2026, 8, 20, index, tzinfo=timezone.utc)
        await store.save(recent)

    found = await store.search_history(
        created_after=datetime(2016, 8, 20, tzinfo=timezone.utc),
        created_before=datetime(2016, 8, 21, tzinfo=timezone.utc),
        text="client Atlas",
        limit=3,
    )
    assert [item.id for item in found] == [old.id]
    await database.close()


@pytest.mark.asyncio
async def test_runtime_answers_dated_history_from_original_task_with_zero_model(tmp_path) -> None:
    harness = await build_runtime(tmp_path / "runtime.db")
    store = MemoryStore(harness.database)
    harness.runtime.memory_store = store
    harness.runtime.memory_retriever = MemoryRetriever(store, DisabledEmbeddingProvider())

    old = Task.from_create(TaskCreate(user_request="Client Atlas chose the blue launch plan"))
    old.created_at = datetime(2016, 8, 20, 9, tzinfo=timezone.utc)
    old.status = TaskStatus.COMPLETED
    await harness.task_store.save(old)

    recall = await harness.runtime.create_task(TaskCreate(
        user_request="What did I tell you on 2016-08-20 about client Atlas?"
    ))
    completed = await wait_for_status(
        harness.task_store, recall.id, {TaskStatus.COMPLETED, TaskStatus.FAILED}, timeout=3,
    )
    assert completed.status == TaskStatus.COMPLETED
    assert completed.assigned_model == "local-history-v1"
    assert "Client Atlas chose the blue launch plan" in completed.result.response
    assert completed.result.usage.total_tokens == 0
    await close_harness(harness)


def test_context_scope_is_copied_into_the_durable_task() -> None:
    task = Task.from_create(TaskCreate(
        user_request="Open it",
        context_id="remote:session-7",
        source="remote:phone-1",
        correlation_id="rcmd-9",
    ))
    assert task.context_id == "remote:session-7"
    assert task.source == "remote:phone-1"
    assert task.correlation_id == "rcmd-9"


def test_active_referents_do_not_cross_desktop_and_phone_contexts() -> None:
    cognitive = CognitiveRuntime(None, None)
    desktop = Task.from_create(TaskCreate(
        user_request="Open desktop site", context_id="desktop:primary",
    ))
    desktop.status = TaskStatus.COMPLETED
    phone = Task.from_create(TaskCreate(
        user_request="Open phone site", context_id="remote:session-7",
        source="remote:phone-1",
    ))
    phone.status = TaskStatus.COMPLETED
    cognitive.record_observation(
        task=desktop,
        result=SimpleNamespace(structured_data={"url": "https://desktop.example"}),
    )
    cognitive.record_observation(
        task=phone,
        result=SimpleNamespace(structured_data={"url": "https://phone.example"}),
    )
    assert cognitive.resolve_reference("open it", context_id="desktop:primary") == "https://desktop.example"
    assert cognitive.resolve_reference("open it", context_id="remote:session-7") == "https://phone.example"


@pytest.mark.asyncio
async def test_ten_independent_tasks_keep_unique_ownership_and_terminal_events(tmp_path) -> None:
    harness = await build_runtime(tmp_path / "concurrent.db")
    created = await asyncio.gather(*(
        harness.runtime.create_task(TaskCreate(
            user_request=f"Tell me a short acknowledgement for independent task number {index}",
            context_id=f"desktop:burst:{index}",
        ))
        for index in range(10)
    ))
    finished = await asyncio.gather(*(
        wait_for_status(
            harness.task_store,
            task.id,
            {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
            timeout=5,
        )
        for task in created
    ))
    assert len({task.id for task in finished}) == 10
    assert all(task.status == TaskStatus.COMPLETED for task in finished)
    terminal_counts = {
        task.id: sum(
            1 for event in harness.event_bus.history
            if event.task_id == task.id
            and event.type.value in {"task_completed", "task_failed", "task_cancelled"}
        )
        for task in finished
    }
    assert set(terminal_counts.values()) == {1}
    await close_harness(harness)


@pytest.mark.asyncio
async def test_natural_schedule_is_persisted_and_verified_through_task_runtime(tmp_path) -> None:
    harness = await build_runtime(tmp_path / "schedule.db")
    harness.runtime.automation_store = AutomationStore(harness.database)
    created = await harness.runtime.create_task(TaskCreate(
        user_request="Every weekday at 9:30 AM, show my system status"
    ))
    finished = await wait_for_status(
        harness.task_store, created.id, {TaskStatus.COMPLETED, TaskStatus.FAILED}, timeout=3,
    )
    assert finished.status == TaskStatus.COMPLETED
    assert finished.assigned_model == "local-scheduler-v1"
    assert finished.metadata["goal_verification"]["status"] == "VERIFIED_COMPLETE"
    automation_id = finished.result.structured_data["automation_id"]
    persisted = await harness.runtime.automation_store.get(automation_id)
    assert persisted.condition["command"] == "show my system status"
    assert persisted.cron_expression == "30 9 * * 1-5"
    await close_harness(harness)
