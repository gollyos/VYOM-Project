"""Tests for the self-healing retry loop (TaskRuntime._maybe_self_heal /
_retry_chain_depth) - a transient failure (FailureAnalyzer's
retriable=True rules) gets one automatic fresh attempt as a new linked
task, bounded by RETRY_CHAIN_LIMIT.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.learning.failure_analyzer import FailureAnalyzer
from app.schemas.tasks import ActionProvenance, Task

from .helpers import build_runtime, close_harness


class _FakeImprovementEngine:
    def __init__(self):
        self.failures = FailureAnalyzer()


class _FakeIntelligenceEngine:
    def __init__(self):
        self.improvement = _FakeImprovementEngine()


@pytest.fixture
async def harness(tmp_path: Path):
    harness = await build_runtime(tmp_path / "brain.db")
    harness.runtime.intelligence_engine = _FakeIntelligenceEngine()
    yield harness
    await close_harness(harness)


async def _save_failed_task(harness, *, error: str, parent_task_id: str | None = None) -> Task:
    task = Task(goal="x", user_request="do the thing", error=error, parent_task_id=parent_task_id)
    from app.schemas.tasks import TaskStatus
    task.status = TaskStatus.FAILED
    await harness.task_store.save(task)
    return task


@pytest.mark.asyncio
async def test_transient_failure_spawns_a_retry_task(harness):
    failed = await _save_failed_task(harness, error="No visible window matching 'Calculator'")
    await harness.runtime._maybe_self_heal(failed)

    all_tasks = await harness.task_store.list(limit=50)
    retries = [t for t in all_tasks if t.parent_task_id == failed.id]
    assert len(retries) == 1
    assert retries[0].user_request == failed.user_request
    assert retries[0].metadata.get("provenance") == ActionProvenance.SELF_HEALING_RETRY.value


@pytest.mark.asyncio
async def test_non_retriable_failure_does_not_spawn_a_retry(harness):
    failed = await _save_failed_task(harness, error="Cannot find module react")
    await harness.runtime._maybe_self_heal(failed)

    all_tasks = await harness.task_store.list(limit=50)
    retries = [t for t in all_tasks if t.parent_task_id == failed.id]
    assert retries == []


@pytest.mark.asyncio
async def test_unrecognised_error_does_not_spawn_a_retry(harness):
    failed = await _save_failed_task(harness, error="something completely unclassified happened")
    await harness.runtime._maybe_self_heal(failed)

    all_tasks = await harness.task_store.list(limit=50)
    retries = [t for t in all_tasks if t.parent_task_id == failed.id]
    assert retries == []


@pytest.mark.asyncio
async def test_retry_chain_stops_at_the_limit(harness):
    """A chain that has already retried RETRY_CHAIN_LIMIT times must
    not retry again, even though the latest failure is itself
    transient - this is the bound against looping forever on a target
    that never stabilizes."""
    root = await _save_failed_task(harness, error="No visible window matching 'Calculator'")
    current = root
    for _ in range(harness.runtime.RETRY_CHAIN_LIMIT):
        current = await _save_failed_task(
            harness, error="No visible window matching 'Calculator'", parent_task_id=current.id,
        )

    before = await harness.task_store.list(limit=50)
    await harness.runtime._maybe_self_heal(current)
    after = await harness.task_store.list(limit=50)

    # No NEW retry task was created once the chain hit its limit.
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_retry_chain_depth_counts_correctly(harness):
    root = await _save_failed_task(harness, error="timeout")
    child = await _save_failed_task(harness, error="timeout", parent_task_id=root.id)
    grandchild = await _save_failed_task(harness, error="timeout", parent_task_id=child.id)

    assert await harness.runtime._retry_chain_depth(root) == 0
    assert await harness.runtime._retry_chain_depth(child) == 1
    assert await harness.runtime._retry_chain_depth(grandchild) == 2


@pytest.mark.asyncio
async def test_no_intelligence_engine_never_raises(tmp_path: Path):
    """A Brain instance without intelligence_engine attached (the
    default) must silently skip self-healing, never crash the failure
    handler."""
    harness = await build_runtime(tmp_path / "brain2.db")
    try:
        failed = await _save_failed_task(harness, error="No visible window matching 'Calculator'")
        await harness.runtime._maybe_self_heal(failed)  # must not raise
    finally:
        await close_harness(harness)


@pytest.mark.asyncio
async def test_learn_skill_intent_is_never_gated_by_a_stray_l2_keyword(tmp_path: Path):
    """'learn how to deploy: ...' contains the word 'deploy', which the
    generic PermissionEngine.classify() floors at L2 (consequential
    external action) elsewhere in the codebase - but learn_skill only
    ever writes a local TESTING-status skill file, so it must be capped
    to L1 (no approval gate) regardless of words inside the described
    workflow."""
    from app.schemas.tasks import PermissionLevel, TaskCreate

    harness = await build_runtime(tmp_path / "brain3.db")
    try:
        task = await harness.runtime.create_task(TaskCreate(
            user_request="learn how to deploy: 1. build 2. test 3. push",
            context_id="desktop:primary",
        ))
        from .helpers import wait_for_status
        from app.schemas.tasks import TaskStatus

        final = await wait_for_status(
            harness.task_store, task.id,
            {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.NEEDS_APPROVAL}, timeout=5,
        )
        assert final.permission_level == PermissionLevel.L1
        assert final.requires_approval is False
    finally:
        await close_harness(harness)
