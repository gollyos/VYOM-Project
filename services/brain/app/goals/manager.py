from __future__ import annotations

from datetime import datetime, timezone

from .milestones import MilestoneService
from .planner import GoalPlan, GoalPlanner
from .progress import GoalEvidence, GoalProgressEvaluator, GoalProgressResult
from .schemas import Goal, GoalCategory, GoalPriority, GoalStatus
from .store import GoalStore

_VALID_TRANSITIONS: dict[GoalStatus, set[GoalStatus]] = {
    GoalStatus.IDEA: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.ACTIVE: {GoalStatus.PAUSED, GoalStatus.BLOCKED, GoalStatus.COMPLETED, GoalStatus.ABANDONED},
    GoalStatus.PAUSED: {GoalStatus.ACTIVE, GoalStatus.ABANDONED},
    GoalStatus.BLOCKED: {GoalStatus.ACTIVE, GoalStatus.PAUSED, GoalStatus.ABANDONED},
    GoalStatus.COMPLETED: set(),
    GoalStatus.ABANDONED: {GoalStatus.IDEA},
}


class InvalidGoalTransitionError(ValueError):
    pass


class GoalManager:
    def __init__(self, store: GoalStore, milestone_service: MilestoneService, planner: GoalPlanner, progress_evaluator: GoalProgressEvaluator | None = None):
        self.store = store
        self.milestones = milestone_service
        self.planner = planner
        self.progress_evaluator = progress_evaluator or GoalProgressEvaluator()

    async def create(
        self, title: str, *, description: str = "", category: GoalCategory = GoalCategory.OTHER,
        priority: GoalPriority = GoalPriority.MEDIUM, motivation: str | None = None,
    ) -> tuple[Goal, GoalPlan]:
        goal = Goal(title=title, description=description, category=category, priority=priority, motivation=motivation, status=GoalStatus.ACTIVE)
        plan = self.planner.plan(title, category)
        for draft in plan.milestones:
            await self.milestones.create(goal.id, draft.title, draft.target)
        goal.next_action = plan.next_actions[0] if plan.next_actions else None
        await self.store.save(goal)
        return goal, plan

    async def get(self, goal_id: str) -> Goal:
        goal = await self.store.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        return goal

    async def list(self, status: GoalStatus | None = None) -> list[Goal]:
        return await self.store.list(status)

    async def transition(self, goal_id: str, new_status: GoalStatus, *, reason: str | None = None) -> Goal:
        goal = await self.get(goal_id)
        allowed = _VALID_TRANSITIONS.get(goal.status, set())
        if new_status != goal.status and new_status not in allowed:
            raise InvalidGoalTransitionError(f"Cannot move goal from {goal.status.value} to {new_status.value}")
        goal.status = new_status
        if new_status == GoalStatus.BLOCKED and reason:
            goal.blocked_by = [*goal.blocked_by, reason]
        return await self.store.save(goal)

    async def defer(self, goal_id: str) -> Goal:
        """Records that a goal was postponed in favor of other work — the
        input signal for neglect detection (rule 68)."""
        goal = await self.get(goal_id)
        goal.deferred_count += 1
        return await self.store.save(goal)

    async def set_next_action(self, goal_id: str, next_action: str) -> Goal:
        goal = await self.get(goal_id)
        goal.next_action = next_action
        return await self.store.save(goal)

    async def record_progress(self, goal_id: str, evidence: GoalEvidence | None = None) -> GoalProgressResult:
        goal = await self.get(goal_id)
        milestones = await self.milestones.list_for_goal(goal_id)
        result = self.progress_evaluator.evaluate(goal, milestones, evidence)
        goal.progress = result.progress
        goal.progress_basis = result.basis
        if result.progress is not None:
            goal.last_progress_at = datetime.now(timezone.utc)
        await self.store.save(goal)
        return result
