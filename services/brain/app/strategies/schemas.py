from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrategyStatus(str, Enum):
    DRAFT = "draft"
    BACKTESTING = "backtesting"
    VALIDATED = "validated"
    PAPER_TESTING = "paper_testing"
    PAUSED = "paused"
    RETIRED = "retired"


class RuleOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


class IndicatorRule(BaseModel):
    """One structured, inspectable condition: `field` (an indicator name
    computed by `TechnicalAnalysisEngine`/`StrategyEvaluator`) compared
    against either a fixed `value` or another `field`. This is the whole
    strategy DSL — there is no free-form/model-driven execution path
    (rule 24)."""

    field: str
    operator: RuleOperator
    value: float | None = None
    compare_field: str | None = None


class StrategySpec(BaseModel):
    id: str = Field(default_factory=lambda: f"strategy_{uuid4().hex}")
    name: str
    version: str = "1.0"
    universe: list[str] = Field(default_factory=list)
    timeframe: str = "1d"
    entry_rules: list[IndicatorRule] = Field(default_factory=list)
    exit_rules: list[IndicatorRule] = Field(default_factory=list)
    risk_rules: dict[str, float] = Field(default_factory=dict)
    filters: list[IndicatorRule] = Field(default_factory=list)
    parameters: dict[str, float] = Field(default_factory=dict)
    # "manual" (default, rule 18) or "paper_auto" — only ever set by an
    # explicit user action; scheduled automation checks this before it may
    # place any PAPER order for this strategy (docs/PAPER_TRADING.md).
    approval_mode: str = "manual"
    status: StrategyStatus = StrategyStatus.DRAFT
    changelog: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def validate_structure(self) -> list[str]:
        """Returns a list of validation problems (empty = valid). A
        strategy with no entry rules cannot be evaluated deterministically
        and is rejected (rule 24)."""
        problems: list[str] = []
        if not self.entry_rules:
            problems.append("Strategy has no entry_rules; free-form entry conditions are not supported")
        if not self.exit_rules:
            problems.append("Strategy has no exit_rules")
        if not self.universe:
            problems.append("Strategy has no universe (instruments) defined")
        return problems
