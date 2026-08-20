from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .schemas import Goal, GoalStatus


class GoalHealthReport(BaseModel):
    goal_id: str
    neglected: bool = False
    blocked: bool = False
    reasons: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class GoalEvaluator:
    """Detects neglected/blocked goals from real recorded signals only —
    deferred count and elapsed time since last progress (rule 68). Never
    shames; only states the pattern and offers a concrete option."""

    def __init__(self, *, deferred_threshold: int = 3, stale_days_threshold: int = 21):
        self.deferred_threshold = deferred_threshold
        self.stale_days_threshold = stale_days_threshold

    def evaluate(self, goal: Goal, *, now: datetime | None = None) -> GoalHealthReport:
        current_time = now or datetime.now(timezone.utc)
        reasons: list[str] = []
        neglected = False

        if goal.deferred_count >= self.deferred_threshold:
            neglected = True
            reasons.append(f"This goal has been postponed {goal.deferred_count} time(s)")

        reference = goal.last_progress_at or goal.created_at
        stale_days = (current_time - reference).days
        if goal.status == GoalStatus.ACTIVE and stale_days >= self.stale_days_threshold:
            neglected = True
            reasons.append(f"No recorded progress for {stale_days} day(s)")

        blocked = goal.status == GoalStatus.BLOCKED or bool(goal.blocked_by)
        if blocked and goal.blocked_by:
            reasons.append(f"Blocked by: {', '.join(goal.blocked_by[:3])}")

        recommendation = None
        if neglected:
            recommendation = "Consider protected focus time or delegating part of this goal so it stops losing to urgent work."

        return GoalHealthReport(goal_id=goal.id, neglected=neglected, blocked=blocked, reasons=reasons, recommendation=recommendation)
