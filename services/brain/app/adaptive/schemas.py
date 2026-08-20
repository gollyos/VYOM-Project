from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now

# Source priority: explicit user instruction > verified tool evidence >
# repeated successful experience > model inference (rule 12).
SOURCE_PRIORITY = {"user_instruction": 4, "tool_evidence": 3, "experience": 2, "model_inference": 1}


class StrategyStatus(str, Enum):
    ACTIVE = "active"
    WATCH = "watch"        # promising but under-sampled
    DEGRADED = "degraded"  # recent performance poor; investigate
    PAUSED = "paused"      # not used until re-validated or user resumes
    RETIRED = "retired"


class ReuseAction(str, Enum):
    REUSE = "reuse"
    ADAPT = "adapt"
    REPLAN = "replan"


class EnvironmentChange(BaseModel):
    """A detected change in the operating context that should lower
    confidence in old experiences (rule 9): framework version, API,
    site layout, provider, market volatility, client requirements,
    user preferences."""

    change_id: str = Field(default_factory=lambda: f"envchg_{uuid4().hex[:12]}")
    dimension: str          # e.g. "framework_version", "market_volatility"
    old_value: str = ""
    new_value: str = ""
    detected_at: datetime = Field(default_factory=utc_now)
    impact_domains: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    """One meaningful operational outcome. Operational summaries and
    evidence only — hidden chain-of-thought is never stored."""

    experience_id: str = Field(default_factory=lambda: f"exp_{uuid4().hex[:16]}")
    task_id: str | None = None
    task_type: str = "general"
    task_fingerprint: list[str] = Field(default_factory=list)   # ranked tokens
    context_fingerprint: list[str] = Field(default_factory=list)

    goal: str = ""
    domain: str = "general"
    environment: dict[str, str] = Field(default_factory=dict)   # project, os, provider set...

    models_used: list[str] = Field(default_factory=list)
    agents_used: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)

    strategy_used: str | None = None
    plan_summary: list[str] = Field(default_factory=list)

    result_summary: str = ""
    success: bool = False
    verification_score: float = 0.0

    latency_ms: float = 0.0
    cost: float = 0.0
    retries: int = 0

    failure_type: str | None = None
    failure_signature: str | None = None
    failure_reason: str | None = None

    user_correction: str | None = None
    user_satisfaction_signal: str | None = None

    conditions: dict[str, Any] = Field(default_factory=dict)  # regime, data quality, tool availability...
    created_at: datetime = Field(default_factory=utc_now)
    lesson_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str = "experience"


class ReuseDecision(BaseModel):
    action: ReuseAction
    strategy_id: str | None = None
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    condition_match: float = Field(default=0.0, ge=0, le=1)


class StrategyRecord(BaseModel):
    """A generic reusable approach to a class of tasks (coding bug
    strategy, research strategy, browser recovery strategy, trading
    strategy...). Knows WHEN it works: performance is tracked by
    condition/regime, decayed by recency, and never trusted on tiny
    samples."""

    strategy_id: str = Field(default_factory=lambda: f"strat_{uuid4().hex[:12]}")
    domain: str                                  # coding | research | trading | ...
    name: str
    version: str = "1.0"
    conditions: dict[str, Any] = Field(default_factory=dict)  # task_type, env, regime...
    actions: list[str] = Field(default_factory=list)          # plan outline
    tools: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    risk: str = "low"

    outcomes: list[dict] = Field(default_factory=list)  # {at, success, regime/conditions, score}
    status: StrategyStatus = StrategyStatus.WATCH
    created_at: datetime = Field(default_factory=utc_now)
    last_used: datetime | None = None
    parent_version: str | None = None
    changelog: list[str] = Field(default_factory=list)


class StrategyProposal(BaseModel):
    """Evidence-gated evolution: a new version is proposed, backtested,
    validated out-of-sample, paper-tested — and only promoted if the
    evidence threshold passes. Working strategies are never overwritten
    and nothing ever auto-promotes to live trading."""

    proposal_id: str = Field(default_factory=lambda: f"proppos_{uuid4().hex[:12]}")
    strategy_id: str
    from_version: str
    to_version: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=lambda: ["backtest", "out_of_sample_validation", "paper_comparison"])
    state: str = "proposed"   # proposed -> tested -> validated -> promotable | rejected
    approved_by_user: bool = False


class ExperienceContext(BaseModel):
    """The compact context handed to the planner: a small ranked set of
    experiences, failures, and routing hints — never raw history."""

    similar_experiences: list[dict] = Field(default_factory=list)
    relevant_failures: list[dict] = Field(default_factory=list)
    routing_hints: dict[str, Any] = Field(default_factory=dict)
    reuse_decision: ReuseDecision | None = None
    known_entities: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class ExperimentRecord(BaseModel):
    """Bounded exploration (rule 28/29): small, safe, budget-limited
    A/B comparisons. Never on consequential L3 actions."""

    experiment_id: str = Field(default_factory=lambda: f"expmt_{uuid4().hex[:10]}")
    subject: str                 # "tool:defuddle-vs-playwright" / "model:a-vs-b"
    variants: list[str] = Field(default_factory=list)
    results: dict[str, dict] = Field(default_factory=dict)
    winner: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    active: bool = True
