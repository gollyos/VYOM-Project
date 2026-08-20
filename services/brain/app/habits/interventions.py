from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .schemas import DesiredDirection, PatternInsight

ALLOWED_TYPES = {"reminder", "environment_preparation", "schedule_adjustment", "focus_block", "task_delegation", "reduce_notification_noise", "shutdown_routine"}


class InterventionType(str, Enum):
    REMINDER = "reminder"
    ENVIRONMENT_PREPARATION = "environment_preparation"
    SCHEDULE_ADJUSTMENT = "schedule_adjustment"
    FOCUS_BLOCK = "focus_block"
    TASK_DELEGATION = "task_delegation"
    REDUCE_NOTIFICATION_NOISE = "reduce_notification_noise"
    SHUTDOWN_ROUTINE = "shutdown_routine"


class InterventionSuggestion(BaseModel):
    type: InterventionType
    description: str
    based_on: str


class InterventionEngine:
    """Evidence-based, respectful, concise, practical suggestions
    (rule 45/49). Never states a diagnosis or uses shaming language —
    every suggestion is phrased as an offer, grounded in the supplied
    `PatternInsight`."""

    def suggest(self, habit_name: str, direction: DesiredDirection, insight: PatternInsight | None) -> InterventionSuggestion | None:
        if insight is None:
            return None

        if direction in (DesiredDirection.REDUCE, DesiredDirection.AVOID):
            if "unfinished" in insight.statement.lower() or "unfinished work" in insight.statement.lower():
                return InterventionSuggestion(
                    type=InterventionType.SHUTDOWN_ROUTINE,
                    description="Would you like VYOM to move unfinished planning earlier and add an end-of-day shutdown routine?",
                    based_on=insight.statement,
                )
            return InterventionSuggestion(
                type=InterventionType.REDUCE_NOTIFICATION_NOISE,
                description=f"Pattern detected: {insight.statement}. Would you like VYOM to add a reminder before this window to help redirect attention?",
                based_on=insight.statement,
            )

        if direction == DesiredDirection.BUILD:
            return InterventionSuggestion(
                type=InterventionType.SCHEDULE_ADJUSTMENT,
                description=f"Pattern detected: {insight.statement}. Would you like VYOM to schedule a dedicated block during that window?",
                based_on=insight.statement,
            )

        return InterventionSuggestion(
            type=InterventionType.REMINDER,
            description=f"Pattern detected: {insight.statement}. Would you like a reminder to help maintain this?",
            based_on=insight.statement,
        )
