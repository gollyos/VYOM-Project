from __future__ import annotations

from app.automation.schemas import Automation, AutomationCreate, AutomationType
from app.automation.store import AutomationStore

from .schemas import Routine
from .store import RoutineStore


class RoutineScheduler:
    """Reuses the existing durable Automation Runtime rather than building
    a second scheduler (rule 51, docs/AUTOMATION_ENGINE.md). A routine's
    `schedule` only takes effect once the caller explicitly enables it —
    creating the link here never auto-enables anything."""

    def __init__(self, routine_store: RoutineStore, automation_store: AutomationStore):
        self.routine_store = routine_store
        self.automation_store = automation_store

    async def schedule(self, routine: Routine, *, interval_minutes: int, timezone_name: str = "Asia/Calcutta") -> Automation:
        automation = Automation.from_create(AutomationCreate(
            name=f"Routine: {routine.name}", type=AutomationType.RECURRING, action="run_routine",
            interval_minutes=interval_minutes, timezone=timezone_name, condition={"routine_id": routine.id},
            permission_level="L1",
        ))
        await self.automation_store.save(automation)
        routine.automation_id = automation.id
        routine.schedule = f"every {interval_minutes} minute(s)"
        await self.routine_store.save(routine)
        return automation
