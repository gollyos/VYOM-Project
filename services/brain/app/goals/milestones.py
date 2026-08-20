from __future__ import annotations

from datetime import datetime

from .schemas import Milestone, MilestoneStatus
from .store import MilestoneStore


class MilestoneService:
    def __init__(self, store: MilestoneStore):
        self.store = store

    async def create(self, goal_id: str, title: str, target: str, *, deadline: datetime | None = None) -> Milestone:
        return await self.store.save(Milestone(goal_id=goal_id, title=title, target=target, deadline=deadline))

    async def list_for_goal(self, goal_id: str) -> list[Milestone]:
        return await self.store.list_for_goal(goal_id)

    async def mark_done(self, milestone_id: str, *, evidence: list[str]) -> Milestone:
        milestone = await self._require(milestone_id)
        if not evidence:
            raise ValueError("A milestone cannot be marked done without evidence (rule 6)")
        milestone.status = MilestoneStatus.DONE
        milestone.evidence = [*milestone.evidence, *evidence]
        return await self.store.save(milestone)

    async def mark_in_progress(self, milestone_id: str) -> Milestone:
        milestone = await self._require(milestone_id)
        milestone.status = MilestoneStatus.IN_PROGRESS
        return await self.store.save(milestone)

    async def _require(self, milestone_id: str) -> Milestone:
        milestone = await self.store.get(milestone_id)
        if milestone is None:
            raise KeyError(milestone_id)
        return milestone
