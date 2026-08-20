from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WorkloadLevel(str, Enum):
    LIGHT = "light"
    BALANCED = "balanced"
    HEAVY = "heavy"
    OVERLOADED = "overloaded"


class WorkloadSignals(BaseModel):
    """Every field is a real scheduled/active-work signal (rule 23) —
    nothing here is estimated by a model."""

    meeting_hours: float = 0.0
    task_estimate_hours: float = 0.0
    client_work_hours: float = 0.0
    focus_block_hours: float = 0.0
    deadline_count: int = 0
    pending_approvals: int = 0
    agent_dependencies: int = 0
    available_hours: float = 8.0


class WorkloadAssessment(BaseModel):
    level: WorkloadLevel
    committed_hours: float
    available_hours: float
    reasons: list[str] = Field(default_factory=list)


class WorkloadCalculator:
    def calculate(self, signals: WorkloadSignals) -> WorkloadAssessment:
        committed = signals.meeting_hours + signals.task_estimate_hours + signals.client_work_hours + signals.focus_block_hours
        ratio = committed / signals.available_hours if signals.available_hours > 0 else float("inf")

        if ratio < 0.5:
            level = WorkloadLevel.LIGHT
        elif ratio < 0.85:
            level = WorkloadLevel.BALANCED
        elif ratio < 1.15:
            level = WorkloadLevel.HEAVY
        else:
            level = WorkloadLevel.OVERLOADED

        # Deadline/approval/dependency pressure can push an otherwise
        # moderate hour count into overload territory (rule 24 example).
        pressure = signals.deadline_count + signals.pending_approvals + signals.agent_dependencies
        if pressure >= 3 and level in (WorkloadLevel.BALANCED, WorkloadLevel.HEAVY):
            level = WorkloadLevel.OVERLOADED

        reasons = []
        if signals.meeting_hours:
            reasons.append(f"{signals.meeting_hours:.1f} hour(s) of meetings")
        if signals.deadline_count:
            reasons.append(f"{signals.deadline_count} deadline(s)")
        if signals.client_work_hours:
            reasons.append(f"{signals.client_work_hours:.1f} hour(s) of client work")
        if signals.pending_approvals:
            reasons.append(f"{signals.pending_approvals} pending approval(s)")
        if signals.agent_dependencies:
            reasons.append(f"{signals.agent_dependencies} agent dependency/dependencies")

        return WorkloadAssessment(level=level, committed_hours=round(committed, 2), available_hours=signals.available_hours, reasons=reasons)
