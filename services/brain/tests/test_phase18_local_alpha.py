from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.reliability.checkpoints import TaskCheckpoint
from app.schemas.approvals import PermissionLevel
from app.schemas.tasks import Task, TaskStatus


def _settings(base: Path) -> Settings:
    return Settings(
        database_path=base / "phase18.db", skills_root=base / "skills", agents_root=base / "agents",
        audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
        artifacts_root=base / "artifacts", backup_root=base / "backups",
    )


# -- crash-recovery ordering: consequential work must never be blindly restarted --


async def test_consequential_task_with_evidence_is_not_blindly_restarted():
    """Reproduces the exact bug found in Phase 18 verification: main.py used
    to call resume_incomplete_tasks() BEFORE recovery_service.recover() had
    a chance to flag a consequential task as needs_review, so a task with
    evidence of an already-taken external action got silently re-executed
    on every restart regardless of what recovery decided. This proves the
    fix: recovery now runs first and gates what gets restarted."""
    with tempfile.TemporaryDirectory(prefix="vyom-recovery-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = _settings(base)

        # Boot 1: simulate a consequential task that was mid-flight (e.g. an
        # email send) when the process was killed uncleanly - a checkpoint
        # exists with evidence of a real external action already taken.
        with TestClient(create_app(settings)) as client:
            state = client.app.state
            task = Task(
                goal="Send the client status email", user_request="send the client status email",
                status=TaskStatus.EXECUTING, permission_level=PermissionLevel.L2,
            )
            await state.task_store.save(task)
            await state.checkpoint_store.save(TaskCheckpoint(
                task_id=task.id,
                evidence_references=["email_send_confirmation:msg_abc123"],
                completed_tool_calls=[{"tool": "email", "action": "send"}],
            ))
            task_id = task.id

        # Boot 2 (same DB, fresh process): the real main.py startup path
        # runs. The task must be parked for review, NOT silently restarted.
        with TestClient(create_app(settings)) as client2:
            state2 = client2.app.state
            restarted = await state2.task_store.get(task_id)
            assert restarted.status == TaskStatus.PAUSED, (
                f"consequential task with evidence was restarted instead of paused for review "
                f"(status={restarted.status})"
            )
            decisions = {d["task_id"]: d for d in state2.last_recovery_decisions}
            assert decisions[task_id]["action"] == "needs_review"
            assert decisions[task_id]["consequential"] is True


async def test_safe_task_with_checkpoint_and_no_evidence_is_restarted():
    """The other half of the same fix: a task that recovery clears (a
    checkpoint exists, no evidence of an external action already taken)
    must still actually resume - the fix must not become "never restart
    anything."""
    with tempfile.TemporaryDirectory(prefix="vyom-recovery-safe-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = _settings(base)

        with TestClient(create_app(settings)) as client:
            state = client.app.state
            task = Task(
                goal="Summarize the project README", user_request="summarize the project readme",
                status=TaskStatus.EXECUTING, permission_level=PermissionLevel.L0,
            )
            await state.task_store.save(task)
            await state.checkpoint_store.save(TaskCheckpoint(task_id=task.id))  # no evidence, no tool calls
            task_id = task.id

        with TestClient(create_app(settings)) as client2:
            state2 = client2.app.state
            decisions = {d["task_id"]: d for d in state2.last_recovery_decisions}
            assert decisions[task_id]["action"] == "resume"
            restarted = await state2.task_store.get(task_id)
            # Cleared for restart means it must NOT be left parked as
            # PAUSED (the fix's skip-path) - it was handed back to the
            # runtime, whatever happens to it next as a hand-built fake task.
            assert restarted.status != TaskStatus.PAUSED


# -- mission pack + coding executor project-root wiring --


# -- onboarding contract: the exact wire shape the frontend now relies on --


def test_setup_status_fresh_launch_includes_full_step_list():
    """Regression test for a real Phase 18 bug: the frontend's SetupStatus
    interface expected a `steps: SetupStep[]` array (id/title/description/
    required/status) and a `nextStep` it could look up in that array, but
    the backend's /api/setup/status only ever returned summary string-ID
    lists (`completed`/`skipped`/`pending`) with no `steps` field at all -
    crashing the whole app on first load. Confirms the real fix: `steps`
    is present, non-empty, and each entry has everything the UI needs."""
    with tempfile.TemporaryDirectory(prefix="vyom-onboard-fresh-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            response = client.get("/api/setup/status")
            assert response.status_code == 200
            data = response.json()

            assert data["finished"] is False
            assert data["needs_onboarding"] is True
            assert data["next_step"] == "intro"
            assert isinstance(data["steps"], list) and len(data["steps"]) == 13
            first = data["steps"][0]
            assert first["id"] == "intro"
            assert first["status"] == "pending"
            assert isinstance(first["title"], str) and first["title"]
            assert isinstance(first["description"], str) and first["description"]
            assert isinstance(first["required"], bool)


def test_setup_status_partial_completion_reflects_per_step_state():
    with tempfile.TemporaryDirectory(prefix="vyom-onboard-partial-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            client.post("/api/setup/steps/intro/complete", json={"data": {}})
            client.post("/api/setup/steps/preferences/complete", json={"data": {"name": "Gunjan"}})
            client.post("/api/setup/steps/voice_test/skip")

            data = client.get("/api/setup/status").json()
            by_id = {step["id"]: step for step in data["steps"]}
            assert by_id["intro"]["status"] == "completed"
            assert by_id["preferences"]["status"] == "completed"
            assert by_id["voice_test"]["status"] == "skipped"
            assert by_id["microphone"]["status"] == "pending"
            assert data["next_step"] == "microphone"
            assert data["needs_onboarding"] is True


def test_setup_status_completed_onboarding():
    with tempfile.TemporaryDirectory(prefix="vyom-onboard-done-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            from app.setup.schemas import REQUIRED_STEPS, SetupStepId

            for step_id in SetupStepId:
                if step_id in REQUIRED_STEPS:
                    client.post(f"/api/setup/steps/{step_id.value}/complete", json={"data": {}})
                else:
                    client.post(f"/api/setup/steps/{step_id.value}/skip")

            data = client.get("/api/setup/status").json()
            assert data["finished"] is True
            assert data["needs_onboarding"] is False
            assert data["next_step"] is None
            assert all(step["status"] in ("completed", "skipped") for step in data["steps"])


def test_setup_status_completing_integrations_step_works_while_disconnected():
    """The Gmail/Calendar integration step must complete/skip normally
    even though those integrations are disconnected by default - onboarding
    is never blocked on an optional integration actually being connected."""
    with tempfile.TemporaryDirectory(prefix="vyom-onboard-integrations-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            integrations = client.get("/api/setup/integrations").json()
            assert all(item["status"] == "disconnected" for item in integrations)

            response = client.post("/api/setup/steps/integrations/skip")
            assert response.status_code == 200
            data = response.json()
            by_id = {step["id"]: step for step in data["steps"]}
            assert by_id["integrations"]["status"] == "skipped"


async def test_coding_mission_pack_resolves_project_root_from_state():
    """Regression test for a real bug found in Phase 18 verification:
    mission_packs.py's coding executor referenced state.settings_database_path,
    which was never actually set on application.state (the coding mission's
    first step failed on every run with AttributeError). Confirms the fix:
    the attribute exists and the full mission completes."""
    from app.runtime.mission_packs import MISSION_PACKS

    with tempfile.TemporaryDirectory(prefix="vyom-coding-root-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = _settings(base)
        with TestClient(create_app(settings)) as client:
            state = client.app.state
            assert hasattr(state, "settings_database_path")
            mission = await state.run_mission_pack("coding", state, goal=MISSION_PACKS["coding"].goal_template)
            assert mission.status == "completed"
            # Step COUNT is not the property under test and is not stable:
            # ModelAssistedPlanner consults a real model for a complex
            # mission when one is configured, and falls back to the
            # deterministic decomposition when none is. Both are correct.
            # What this regression test pins is that every step actually
            # ran and verified - the original bug failed the first step
            # with AttributeError on every run.
            assert len(mission.completed) >= 3
            assert all(step.verified for step in mission.completed)


# -- Phase 18.1: TaskOwnershipRegistry wired at the task-execution chokepoint --


def _consequential_task(goal: str = "send email with the client status") -> Task:
    # "send email" is a real L2 marker in app/security/permission_engine.py -
    # task_runtime.run() reclassifies permission_level from user_request
    # text regardless of what the Task was constructed with, so the
    # phrasing here must genuinely trigger L2, not just look consequential.
    return Task(goal=goal, user_request=goal, approval_granted=True)


async def test_concurrent_consequential_task_execution_runs_exactly_once():
    """Two concurrent attempts to run the SAME consequential task_id (a
    real race: e.g. a duplicate API resume alongside an in-process retry)
    must result in exactly one execution reaching past the ownership
    guard - the other is paused, never silently re-executed."""
    with tempfile.TemporaryDirectory(prefix="vyom-idem-concurrent-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            state = client.app.state
            task = _consequential_task()
            await state.task_store.save(task)

            import asyncio
            await asyncio.gather(state.runtime.run(task.id), state.runtime.run(task.id))

            duplicate_events = [
                event for event in state.event_bus.history
                if event.task_id == task.id and "Duplicate consequential execution prevented" in event.human_readable_message
            ]
            assert len(duplicate_events) == 1, (
                f"expected exactly one blocked duplicate attempt, got {len(duplicate_events)}"
            )
            assert await state.ownership_registry.was_executed(f"task_exec:{task.id}")


async def test_duplicate_task_submission_after_brain_restart_runs_exactly_once():
    """The other half of the crash-recovery-ordering fix: even if a
    consequential task somehow got resubmitted/resumed after a restart
    (defense in depth beyond the recovery-decision gate), the durable
    idempotency record (survives the restart, unlike the in-process
    `active` dict) blocks a second real execution."""
    with tempfile.TemporaryDirectory(prefix="vyom-idem-restart-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = _settings(base)

        with TestClient(create_app(settings)) as client:
            state = client.app.state
            task = _consequential_task()
            await state.task_store.save(task)
            await state.runtime.run(task.id)
            task_id = task.id

        # Boot 2: same DB, fresh process/state - simulate a duplicate
        # resubmission of the identical task_id after a restart.
        with TestClient(create_app(settings)) as client2:
            state2 = client2.app.state
            resubmitted = await state2.task_store.get(task_id)
            resubmitted.status = TaskStatus.QUEUED  # simulate a resubmission attempt
            await state2.task_store.save(resubmitted)
            await state2.runtime.run(task_id)

            duplicate_events = [
                event for event in state2.event_bus.history
                if event.task_id == task_id and "Duplicate consequential execution prevented" in event.human_readable_message
            ]
            assert len(duplicate_events) == 1


async def test_non_consequential_task_is_never_gated_by_ownership():
    """L0/L1 tasks are not consequential - they must never be blocked by
    the ownership guard, including on a genuine re-run."""
    with tempfile.TemporaryDirectory(prefix="vyom-idem-safe-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        with TestClient(create_app(_settings(base))) as client:
            state = client.app.state
            task = Task(goal="Summarize the README", user_request="summarize the readme")
            await state.task_store.save(task)
            await state.runtime.run(task.id)

            duplicate_events = [
                event for event in state.event_bus.history
                if "Duplicate consequential execution prevented" in event.human_readable_message
            ]
            assert len(duplicate_events) == 0
