from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationType(str, Enum):
    ONE_TIME = "one_time"
    SCHEDULED = "scheduled"
    RECURRING = "recurring"
    CONDITIONAL = "conditional"


class AutomationStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    DISABLED = "disabled"


class AutomationBudget(BaseModel):
    max_runs_per_day: int = Field(default=10, ge=1, le=100)
    max_runtime_seconds: int = Field(default=60, ge=1, le=900)
    max_tool_calls: int = Field(default=5, ge=0, le=50)
    max_cost_tier: str = "free"


class AutomationCreate(BaseModel):
    name: str
    type: AutomationType
    action: str
    permission_level: str = "L1"
    timezone: str = "Asia/Calcutta"
    run_at: datetime | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    cron_expression: str | None = None
    condition: dict[str, Any] | None = None
    budget: AutomationBudget = Field(default_factory=AutomationBudget)

    @model_validator(mode="after")
    def validate_schedule(self) -> "AutomationCreate":
        ZoneInfo(self.timezone)
        if self.type in {AutomationType.ONE_TIME, AutomationType.SCHEDULED} and self.run_at is None:
            raise ValueError("run_at is required for one-time and scheduled automations")
        if self.type == AutomationType.RECURRING:
            if (self.interval_minutes is None) == (self.cron_expression is None):
                raise ValueError("Recurring automations require exactly one of interval_minutes or cron_expression")
            if self.cron_expression:
                from .cron import parse_cron

                parse_cron(self.cron_expression)
        if self.type == AutomationType.CONDITIONAL and not self.condition:
            raise ValueError("condition is required for conditional automations")
        if self.permission_level in {"L2", "L3"} and self.action != "run_vyom_command":
            raise ValueError("Consequential automation actions require per-run approval and cannot be auto-enabled")
        if self.action == "run_vyom_command" and not str((self.condition or {}).get("command", "")).strip():
            raise ValueError("run_vyom_command requires condition.command")
        return self


class Automation(AutomationCreate):
    id: str = Field(default_factory=lambda: f"automation_{uuid4().hex}")
    status: AutomationStatus = AutomationStatus.ACTIVE
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    run_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_create(cls, request: AutomationCreate) -> "Automation":
        next_run = request.run_at
        if request.type == AutomationType.RECURRING:
            if request.cron_expression:
                from .cron import next_cron_after

                next_run = next_cron_after(request.cron_expression, utc_now(), request.timezone)
            else:
                next_run = utc_now() + timedelta(minutes=request.interval_minutes or 1)
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=ZoneInfo(request.timezone)).astimezone(timezone.utc)
        return cls(**request.model_dump(), next_run_at=next_run)

    def advance(self, completed_at: datetime) -> None:
        self.last_run_at = completed_at
        self.run_count += 1
        self.updated_at = completed_at
        if self.type in {AutomationType.ONE_TIME, AutomationType.SCHEDULED}:
            self.status = AutomationStatus.COMPLETED
            self.next_run_at = None
        elif self.type == AutomationType.RECURRING:
            if self.cron_expression:
                from .cron import next_cron_after

                self.next_run_at = next_cron_after(self.cron_expression, completed_at, self.timezone)
            else:
                self.next_run_at = completed_at + timedelta(minutes=self.interval_minutes or 1)


class AutomationRun(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex}")
    automation_id: str
    idempotency_key: str
    status: str = "running"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
