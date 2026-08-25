from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .approvals import PermissionLevel
from .results import ExecutionResult, VerificationResult
from .routing import RoutingDecision


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskDomain(str, Enum):
    GENERAL = "general"
    PLANNING = "planning"
    CODING = "coding"
    RESEARCH = "research"
    AGENCY = "agency"
    COMMUNICATION = "communication"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    SYSTEM = "system"
    PERSONAL = "personal"
    FINANCE = "finance"


class ActionProvenance(str, Enum):
    """Why an external app/window/browser action is allowed to run.

    Every execution path that can act on the world (launch/close an app,
    open a browser profile/tab, click/type/scroll a page, run a shell
    command) must trace back to exactly one of these. No valid provenance
    -> the action is denied, not simulated, not skipped-with-a-warning."""

    USER_COMMAND = "USER_COMMAND"
    APPROVED_SCHEDULE = "APPROVED_SCHEDULE"
    APPROVED_AUTOMATION = "APPROVED_AUTOMATION"
    CURRENT_GOAL_RECOVERY = "CURRENT_GOAL_RECOVERY"
    SYSTEM_SAFETY_ACTION = "SYSTEM_SAFETY_ACTION"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    WAITING = "waiting"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TaskProfile(BaseModel):
    domain: TaskDomain = TaskDomain.GENERAL
    complexity: int = Field(default=1, ge=1, le=5)
    latency_priority: str = "normal"
    criticality: str = "low"
    needs: set[str] = Field(default_factory=lambda: {"structured_output"})
    privacy: str = "normal"
    deterministic: bool = False
    intent: str = "general"
    #: Whether VYOM should run this task in the BACKGROUND (its own window
    #: minimized/hidden, headless browser, invisible) or VISUALLY on the
    #: user's screen (a real non-headless browser, real OS mouse). Decided
    #: per-task by app/execution/visibility.classify_visibility() so VYOM
    #: KNOWS how to present the work before it starts (see
    #: TaskClassifier). Defaults to 'background' — the safe, non-disruptive
    #: direction unless the user explicitly asked to watch.
    visibility: str = "background"


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: f"step_{uuid4().hex[:10]}")
    title: str
    summary: str
    dependencies: list[str] = Field(default_factory=list)
    status: str = "pending"


class TaskBudget(BaseModel):
    max_cost_tier: str = "medium"
    max_fallbacks: int = Field(default=2, ge=0, le=5)
    max_runtime_seconds: int = Field(default=120, ge=1)


class TaskCreate(BaseModel):
    goal: str | None = None
    user_request: str = Field(min_length=1, max_length=20_000)
    priority: str = "normal"
    parent_task_id: str | None = None
    # Commands from desktop, a paired phone session, a schedule, or a
    # recovery all enter the same TaskRuntime but keep distinct context
    # scopes. This prevents "it / same tab" in one source from resolving
    # to an object observed by another concurrent source.
    context_id: str = Field(default="desktop:primary", min_length=1, max_length=200)
    source: str = Field(default="desktop", min_length=1, max_length=120)
    correlation_id: str | None = Field(default=None, max_length=200)
    budget: TaskBudget = Field(default_factory=TaskBudget)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: f"task_{uuid4().hex}")
    goal: str
    user_request: str
    domain: TaskDomain = TaskDomain.GENERAL
    complexity: int = Field(default=1, ge=1, le=5)
    priority: str = "normal"
    criticality: str = "low"
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parent_task_id: str | None = None
    context_id: str = "desktop:primary"
    source: str = "desktop"
    correlation_id: str | None = None
    subtasks: list[str] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    current_step: int = 0
    progress: float = Field(default=0, ge=0, le=1)
    assigned_model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    requires_tools: bool = False
    requires_approval: bool = False
    permission_level: PermissionLevel = PermissionLevel.L0
    approval_id: str | None = None
    approval_granted: bool = False
    budget: TaskBudget = Field(default_factory=TaskBudget)
    profile: TaskProfile | None = None
    routing: RoutingDecision | None = None
    result: ExecutionResult | None = None
    verification: VerificationResult | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_create(cls, request: TaskCreate) -> "Task":
        return cls(
            goal=request.goal or request.user_request,
            user_request=request.user_request,
            priority=request.priority,
            parent_task_id=request.parent_task_id,
            context_id=request.context_id,
            source=request.source,
            correlation_id=request.correlation_id,
            budget=request.budget,
        )
