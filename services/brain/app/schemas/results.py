from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .routing import UsageRecord


class ExecutionResult(BaseModel):
    response: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    ui_composition: dict[str, Any] | None = None
    evidence: list[str] = Field(default_factory=list)
    usage: UsageRecord = Field(default_factory=UsageRecord)


class VerificationResult(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    summary: str
    evidence: list[str] = Field(default_factory=list)

