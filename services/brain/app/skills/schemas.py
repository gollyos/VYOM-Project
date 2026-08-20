from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.approvals import PermissionLevel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SkillStatus(str, Enum):
    DRAFT = "draft"
    TESTING = "testing"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    FAILED = "failed"


class SkillStep(BaseModel):
    id: str
    action: str
    capability: str
    tool: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class SkillVerification(BaseModel):
    checks: list[str]
    minimum_score: float = Field(default=1.0, ge=0, le=1)
    require_evidence: bool = True


class SkillFailurePolicy(BaseModel):
    max_retries: int = Field(default=1, ge=0, le=3)
    stop_on_permission_error: bool = True
    stop_on_verification_failure: bool = True


class SkillBudget(BaseModel):
    max_model_calls: int = Field(default=0, ge=0, le=10)
    max_tool_calls: int = Field(default=8, ge=1, le=50)
    max_runtime_seconds: int = Field(default=180, ge=1, le=1800)
    max_cost: float = Field(default=0, ge=0, le=100)


class SkillMetrics(BaseModel):
    executions: int = 0
    successes: int = 0
    failures: int = 0
    verification_score: float = Field(default=0, ge=0, le=1)
    average_runtime_ms: float = 0
    average_cost: float = 0
    common_failure_reason: str | None = None


class SkillSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    category: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str]
    required_tools: list[str]
    required_permissions: PermissionLevel = PermissionLevel.L1
    steps: list[SkillStep] = Field(min_length=1)
    verification: SkillVerification
    failure_policy: SkillFailurePolicy = Field(default_factory=SkillFailurePolicy)
    budget: SkillBudget = Field(default_factory=SkillBudget)
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used: datetime | None = None
    success_rate: float = Field(default=0.5, ge=0, le=1)
    status: SkillStatus = SkillStatus.DRAFT
    previous_version: str | None = None
    metrics: SkillMetrics = Field(default_factory=SkillMetrics)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = {step.id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("Skill step IDs must be unique")
        for step in self.steps:
            if any(dependency not in ids for dependency in step.depends_on):
                raise ValueError(f"Skill step {step.id} has an unknown dependency")
            if step.id in step.depends_on:
                raise ValueError("Skill steps cannot depend on themselves")
        return self


class SkillEvaluation(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    checks: dict[str, bool]
    evidence: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
