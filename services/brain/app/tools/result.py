from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceItem(BaseModel):
    type: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolResult(BaseModel):
    success: bool
    status: ToolStatus
    summary: str
    structured_output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float = Field(default=0, ge=0)

    @classmethod
    def completed(
        cls,
        summary: str,
        *,
        output: dict[str, Any] | None = None,
        evidence: list[EvidenceItem] | None = None,
        warnings: list[str] | None = None,
    ) -> "ToolResult":
        return cls(
            success=True,
            status=ToolStatus.COMPLETED,
            summary=summary,
            structured_output=output or {},
            evidence=evidence or [],
            warnings=warnings or [],
        )
