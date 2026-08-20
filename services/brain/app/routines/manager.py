from __future__ import annotations

from .schemas import Routine
from .store import RoutineStore


class RoutineManager:
    def __init__(self, store: RoutineStore):
        self.store = store

    async def create(self, routine: Routine) -> Routine:
        return await self.store.save(routine)

    async def get(self, routine_id: str) -> Routine:
        routine = await self.store.get(routine_id)
        if routine is None:
            raise KeyError(routine_id)
        return routine

    async def list(self) -> list[Routine]:
        return await self.store.list()

    async def enable(self, routine_id: str) -> Routine:
        """Never called automatically (rule 51) — only in response to an
        explicit user action."""
        routine = await self.get(routine_id)
        routine.enabled = True
        return await self.store.save(routine)

    async def disable(self, routine_id: str) -> Routine:
        routine = await self.get(routine_id)
        routine.enabled = False
        return await self.store.save(routine)
