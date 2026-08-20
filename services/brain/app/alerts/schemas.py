from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AlertConditionType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PERCENTAGE_MOVE = "percentage_move"
    VOLUME_CONDITION = "volume_condition"
    TECHNICAL_CONDITION = "technical_condition"
    PORTFOLIO_DRAWDOWN = "portfolio_drawdown"
    PAPER_POSITION_STOP = "paper_position_stop"
    PAPER_TARGET = "paper_target"
    NEWS_CONDITION = "news_condition"


class AlertCondition(BaseModel):
    type: AlertConditionType
    symbol: str | None = None
    threshold: float | None = None
    field: str | None = None          # e.g. "rsi_14" for technical_condition
    operator: str = "gte"             # gte, lte, gt, lt
    portfolio_id: str | None = None
    keyword: str | None = None        # for news_condition


class AlertStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: f"alert_{uuid4().hex}")
    name: str
    instrument: str | None = None
    condition: AlertCondition
    schedule: str | None = None       # human-readable cadence hint; actual timing owned by AutomationScheduler
    status: AlertStatus = AlertStatus.ENABLED
    cooldown_seconds: float = 3600.0
    last_checked: datetime | None = None
    last_triggered: datetime | None = None
    trigger_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
