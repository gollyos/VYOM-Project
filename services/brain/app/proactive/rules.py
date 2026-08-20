from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProactiveLevel(str, Enum):
    QUIET = "quiet"
    BALANCED = "balanced"
    PROACTIVE = "proactive"


_LEVEL_MIN_IMPORTANCE = {ProactiveLevel.QUIET: 0.9, ProactiveLevel.BALANCED: 0.55, ProactiveLevel.PROACTIVE: 0.3}


class ProactiveSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: f"proactive_{uuid4().hex}")
    title: str
    description: str
    importance: float = Field(ge=0, le=1)
    actionable: bool = True
    auto_handleable: bool = False
    urgency: str = "normal"  # informational | low | normal | important | urgent | critical
    dedupe_key: str = ""
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def compute_dedupe_key(self) -> str:
        return self.dedupe_key or hashlib.sha256(f"{self.title}|{self.description}".encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ProactiveRules:
    default_level: ProactiveLevel
    require_important: bool
    require_actionable: bool
    require_good_timing: bool
    require_not_already_surfaced: bool
    suppress_if_auto_handleable: bool
    require_benefit_exceeds_interruption_cost: bool
    duplicate_window_hours: float
    max_low_priority_per_day: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ProactiveRules":
        proactive = config.get("proactive", {})
        gate = proactive.get("gate", {})
        suppression = proactive.get("suppression", {})
        return cls(
            default_level=ProactiveLevel(proactive.get("default_level", "balanced")),
            require_important=bool(gate.get("require_important", True)),
            require_actionable=bool(gate.get("require_actionable", True)),
            require_good_timing=bool(gate.get("require_good_timing", True)),
            require_not_already_surfaced=bool(gate.get("require_not_already_surfaced", True)),
            suppress_if_auto_handleable=bool(gate.get("suppress_if_auto_handleable", True)),
            require_benefit_exceeds_interruption_cost=bool(gate.get("require_benefit_exceeds_interruption_cost", True)),
            duplicate_window_hours=float(suppression.get("duplicate_window_hours", 24)),
            max_low_priority_per_day=int(suppression.get("max_low_priority_per_day", 3)),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "ProactiveRules":
        return cls.from_config(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def min_importance_for(self, level: ProactiveLevel) -> float:
        return _LEVEL_MIN_IMPORTANCE[level]
