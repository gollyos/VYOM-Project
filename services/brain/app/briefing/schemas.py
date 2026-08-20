from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceSnapshot(BaseModel):
    source: str
    status: str
    detail: str
    observed_at: datetime


class DailyBriefing(BaseModel):
    generated_at: datetime
    summary: str
    metrics: dict[str, int | float | str | None]
    priorities: list[str] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[SourceSnapshot] = Field(default_factory=list)
    incomplete: bool = False
