from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DesiredDirection(str, Enum):
    BUILD = "build"
    REDUCE = "reduce"
    MAINTAIN = "maintain"
    AVOID = "avoid"


class MeasurementType(str, Enum):
    BOOLEAN = "boolean"
    COUNT = "count"
    DURATION_MINUTES = "duration_minutes"


class HabitStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Habit(BaseModel):
    id: str = Field(default_factory=lambda: f"habit_{uuid4().hex}")
    name: str
    category: str = "general"
    desired_direction: DesiredDirection = DesiredDirection.BUILD
    frequency: str = "daily"          # human-readable, e.g. "4x/week"
    target: float | None = None
    measurement_type: MeasurementType = MeasurementType.BOOLEAN
    status: HabitStatus = HabitStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    reminder_policy: dict = Field(default_factory=dict)
    linked_goal: str | None = None


class HabitEventSource(str, Enum):
    MANUAL = "manual"
    CALENDAR = "calendar"
    TASK_RUNTIME = "task_runtime"
    DESKTOP_ACTIVITY = "desktop_activity"
    CONNECTED_SERVICE = "connected_service"
    AUTOMATION = "automation"


class HabitEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"habit_event_{uuid4().hex}")
    habit_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    value: float = 1.0
    source: HabitEventSource = HabitEventSource.MANUAL
    confidence: float = Field(default=1.0, ge=0, le=1)
    note: str | None = None


class PatternInsight(BaseModel):
    """A pattern claim always ships with its own sample size and
    confidence (rule 13) so a weak correlation is never presented as a
    fact."""

    statement: str
    sample_size: int
    confidence: float = Field(ge=0, le=1)
    supporting_events: list[str] = Field(default_factory=list)
    time_range: str
