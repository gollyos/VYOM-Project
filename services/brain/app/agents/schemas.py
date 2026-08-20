from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.approvals import PermissionLevel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus(str, Enum):
    CREATED = "created"
    TESTING = "testing"
    READY = "ready"
    WORKING = "working"
    WAITING = "waiting"
    PAUSED = "paused"
    DISABLED = "disabled"
    FAILED = "failed"
    ARCHIVED = "archived"


class AgentMemoryScope(str, Enum):
    TASK = "task"
    PROJECT = "project"
    CLIENT = "client"
    DOMAIN = "domain"
    USER_APPROVED = "user-approved"


class AgentModelPolicy(BaseModel):
    preferred_capabilities: list[str] = Field(default_factory=list)
    quality_floor: str = "basic"
    cost_priority: str = "high"
    latency_priority: str = "normal"


class AgentBudget(BaseModel):
    max_depth: int = Field(default=1, ge=0, le=4)
    max_parallel_agents: int = Field(default=1, ge=1, le=5)
    max_model_calls: int = Field(default=1, ge=0, le=10)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_runtime_seconds: int = Field(default=240, ge=1, le=1800)
    max_cost: float = Field(default=0.05, ge=0, le=100)


class AgentPerformance(BaseModel):
    missions: int = 0
    successes: int = 0
    failures: int = 0
    success_rate: float = Field(default=0.5, ge=0, le=1)
    verification_score: float = Field(default=0, ge=0, le=1)
    average_cost: float = 0
    average_latency_ms: float = 0
    skill_success: dict[str, float] = Field(default_factory=dict)
    tool_failure_rate: dict[str, float] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str
    role: str
    description: str
    goals: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model_policy: AgentModelPolicy = Field(default_factory=AgentModelPolicy)
    memory_scope: list[AgentMemoryScope] = Field(default_factory=lambda: [AgentMemoryScope.TASK])
    permissions: PermissionLevel = PermissionLevel.L1
    budget: AgentBudget = Field(default_factory=AgentBudget)
    verification_policy: list[str] = Field(default_factory=lambda: ["require evidence"])
    status: AgentStatus = AgentStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    performance: AgentPerformance = Field(default_factory=AgentPerformance)
    current_mission: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_limits(self):
        if self.budget.max_parallel_agents > 3 or self.budget.max_depth > 2:
            raise ValueError("Phase 6 agents are bounded to depth 2 and three parallel delegates")
        return self


class AgentValidation(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    checks: dict[str, bool]
    evidence: list[str] = Field(default_factory=list)


class AgentMission(BaseModel):
    id: str
    parent_task_id: str
    agent_id: str
    goal: str
    depth: int
    status: str = "created"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    evidence: list[str] = Field(default_factory=list)
