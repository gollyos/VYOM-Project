from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RoutineStepType(str, Enum):
    REMINDER = "reminder"
    OPEN_APPLICATION = "open_application"
    SHOW_BRIEFING = "show_briefing"
    START_FOCUS_MODE = "start_focus_mode"
    RUN_AUTOMATION = "run_automation"
    PREPARE_WORKSPACE = "prepare_workspace"
    CREATE_TASK = "create_task"


class RoutineStep(BaseModel):
    type: RoutineStepType
    payload: dict = Field(default_factory=dict)


class Routine(BaseModel):
    id: str = Field(default_factory=lambda: f"routine_{uuid4().hex}")
    name: str
    trigger: str = "manual"           # "manual" | "time:HH:MM" | "before_meeting" | "after_focus" | ...
    steps: list[RoutineStep] = Field(default_factory=list)
    schedule: str | None = None       # human-readable cadence; actual timing owned by AutomationScheduler
    automation_id: str | None = None  # linked Automation, when `schedule` is set
    duration_minutes: float | None = None
    enabled: bool = False             # never auto-enabled (rule 51); explicit user action required
    adaptive: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RoutineStepStatus(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class RoutineStepResult(BaseModel):
    type: RoutineStepType
    status: RoutineStepStatus
    detail: str = ""


class RoutineRunStatus(str, Enum):
    COMPLETED = "completed"
    MISSED = "missed"
    FAILED = "failed"


class RoutineRun(BaseModel):
    id: str = Field(default_factory=lambda: f"routine_run_{uuid4().hex}")
    routine_id: str
    status: RoutineRunStatus = RoutineRunStatus.COMPLETED
    step_results: list[RoutineStepResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    feedback: str | None = None
