from __future__ import annotations

from pydantic import BaseModel

from .schemas import RoutineRunStatus
from .store import RoutineRunStore


class RoutineAdaptationSuggestion(BaseModel):
    routine_id: str
    reason: str
    proposed_change: str
    failure_streak: int


class RoutineAdaptationService:
    """A routine that consistently fails is analyzed, not repeated forever
    unchanged (rule 50). Only recent runs are examined; a single missed
    run never triggers a suggestion."""

    def __init__(self, run_store: RoutineRunStore, *, failure_streak_threshold: int = 3, lookback_runs: int = 10):
        self.run_store = run_store
        self.failure_streak_threshold = failure_streak_threshold
        self.lookback_runs = lookback_runs

    async def evaluate(self, routine_id: str) -> RoutineAdaptationSuggestion | None:
        runs = await self.run_store.list_for_routine(routine_id, limit=self.lookback_runs)
        if not runs:
            return None
        streak = 0
        for run in runs:  # most recent first
            if run.status in (RoutineRunStatus.MISSED, RoutineRunStatus.FAILED):
                streak += 1
            else:
                break
        if streak < self.failure_streak_threshold:
            return None
        return RoutineAdaptationSuggestion(
            routine_id=routine_id,
            reason=f"This routine has been missed or failed {streak} time(s) in a row",
            proposed_change="Consider adjusting the trigger time, shortening the routine, or removing a step that depends on something that isn't reliably available.",
            failure_streak=streak,
        )
