import asyncio

import pytest

from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.schemas.tasks import Task, TaskCreate, TaskStatus

from .helpers import MockProvider, build_runtime, close_harness, local_model, wait_for_status


@pytest.mark.asyncio
async def test_task_persistence_survives_database_reopen(tmp_path):
    path = tmp_path / "persist.db"
    first_database = Database(path)
    await first_database.connect()
    first_store = TaskStore(first_database)
    original = Task(goal="Persist", user_request="Persist this task", status=TaskStatus.PAUSED)
    await first_store.save(original)
    await first_database.close()

    second_database = Database(path)
    await second_database.connect()
    restored = await TaskStore(second_database).get(original.id)
    await second_database.close()
    assert restored is not None
    assert restored.status == TaskStatus.PAUSED
    assert restored.user_request == original.user_request


@pytest.mark.asyncio
async def test_restart_requeues_and_completes_inflight_task(tmp_path):
    path = tmp_path / "restart.db"
    first = await build_runtime(path)
    task = Task(goal="Resume", user_request="Give me a concise general answer", status=TaskStatus.EXECUTING)
    await first.task_store.save(task)
    await close_harness(first)

    second = await build_runtime(path)
    try:
        resumed = await second.runtime.resume_incomplete_tasks()
        assert resumed == 1
        completed = await wait_for_status(second.task_store, task.id, {TaskStatus.COMPLETED})
        assert completed.progress == 1
    finally:
        await close_harness(second)


@pytest.mark.asyncio
async def test_approval_pauses_before_execution(tmp_path):
    harness = await build_runtime(tmp_path / "approval.db")
    try:
        task = await harness.runtime.create_task(TaskCreate(user_request="Send email to the client"))
        waiting = await wait_for_status(harness.task_store, task.id, {TaskStatus.NEEDS_APPROVAL})
        assert waiting.permission_level.value == "L2"
        assert waiting.approval_id
        assert "approval_required" in [event.type.value for event in harness.event_bus.history]
    finally:
        await close_harness(harness)


@pytest.mark.asyncio
async def test_task_cancellation_is_persisted(tmp_path):
    slow = MockProvider("local", delay_seconds=0.3)
    harness = await build_runtime(tmp_path / "cancel.db", providers=[slow])
    try:
        task = await harness.runtime.create_task(TaskCreate(user_request="Give me a concise general answer"))
        await wait_for_status(harness.task_store, task.id, {TaskStatus.EXECUTING})
        await harness.runtime.cancel(task.id)
        cancelled = await wait_for_status(harness.task_store, task.id, {TaskStatus.CANCELLED})
        await asyncio.sleep(0.35)
        final = await harness.task_store.get(task.id)
        assert cancelled.completed_at is not None
        assert final and final.status == TaskStatus.CANCELLED
    finally:
        await close_harness(harness)


@pytest.mark.asyncio
async def test_verification_failure_never_reports_completion(tmp_path):
    harness = await build_runtime(tmp_path / "verify-fail.db")
    try:
        task = Task(
            goal="Fail verification",
            user_request="Give me a concise general answer",
            metadata={"force_verification_failure": True},
        )
        await harness.task_store.save(task)
        await harness.runtime.run(task.id)
        failed = await harness.task_store.get(task.id)
        assert failed and failed.status == TaskStatus.FAILED
        assert failed.verification and not failed.verification.passed
        assert "verification_failed" in [event.type.value for event in harness.event_bus.history]
    finally:
        await close_harness(harness)


@pytest.mark.asyncio
async def test_close_everything_never_calls_a_model(tmp_path):
    local = MockProvider("local")
    harness = await build_runtime(tmp_path / "close.db", providers=[local])
    try:
        task = await harness.runtime.create_task(TaskCreate(user_request="Close everything"))
        completed = await wait_for_status(harness.task_store, task.id, {TaskStatus.COMPLETED})
        assert local.call_count == 0
        assert completed.result and completed.result.structured_data["deterministic"] is True
        assert completed.assigned_model is None
    finally:
        await close_harness(harness)

