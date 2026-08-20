from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from .schemas import Routine, RoutineRun, RoutineRunStatus, RoutineStep, RoutineStepResult, RoutineStepStatus
from .store import RoutineRunStore

StepHandler = Callable[[dict], Awaitable[str]]


class RoutineStepExecutor:
    """Every step type resolves to a real handler bound to an existing,
    already permission-gated service (rule 16) — routines never call the
    OS or an external system directly. A step type with no registered
    handler is honestly reported `unavailable`, never faked as
    completed."""

    def __init__(self, handlers: dict[str, StepHandler] | None = None):
        self.handlers: dict[str, StepHandler] = handlers or {}

    def register(self, step_type: str, handler: StepHandler) -> None:
        self.handlers[step_type] = handler

    async def execute(self, step: RoutineStep) -> RoutineStepResult:
        handler = self.handlers.get(step.type.value)
        if handler is None:
            return RoutineStepResult(type=step.type, status=RoutineStepStatus.UNAVAILABLE, detail="No handler is registered for this step type")
        try:
            detail = await handler(step.payload)
            return RoutineStepResult(type=step.type, status=RoutineStepStatus.COMPLETED, detail=detail)
        except Exception as error:
            return RoutineStepResult(type=step.type, status=RoutineStepStatus.FAILED, detail=str(error))


class RoutineCompletionService:
    def __init__(self, executor: RoutineStepExecutor, run_store: RoutineRunStore):
        self.executor = executor
        self.run_store = run_store

    async def run(self, routine: Routine) -> RoutineRun:
        results = [await self.executor.execute(step) for step in routine.steps]
        status = RoutineRunStatus.FAILED if any(r.status == RoutineStepStatus.FAILED for r in results) else RoutineRunStatus.COMPLETED
        run = RoutineRun(routine_id=routine.id, status=status, step_results=results, completed_at=datetime.now(timezone.utc))
        return await self.run_store.save(run)

    async def record_missed(self, routine: Routine, *, feedback: str | None = None) -> RoutineRun:
        run = RoutineRun(routine_id=routine.id, status=RoutineRunStatus.MISSED, completed_at=datetime.now(timezone.utc), feedback=feedback)
        return await self.run_store.save(run)
