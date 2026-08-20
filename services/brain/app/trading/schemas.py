from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeThesis(BaseModel):
    id: str = Field(default_factory=lambda: f"thesis_{uuid4().hex}")
    instrument: str
    direction: TradeDirection
    time_horizon: str
    thesis: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation: str
    confidence: float = Field(ge=0, le=1)
    data_timestamp: datetime
    created_at: datetime = Field(default_factory=utc_now)


class SetupStatus(str, Enum):
    IDEA = "idea"
    WATCHING = "watching"
    READY_FOR_PAPER = "ready_for_paper"
    PAPER_OPEN = "paper_open"
    PAPER_CLOSED = "paper_closed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class TradeSetup(BaseModel):
    id: str = Field(default_factory=lambda: f"setup_{uuid4().hex}")
    instrument: str
    direction: TradeDirection
    entry_zone: list[float]
    stop: float
    targets: list[float] = Field(default_factory=list)
    risk_reward: float | None = None
    time_horizon: str = "swing (days-weeks)"
    thesis_id: str | None = None
    invalidation: str
    max_risk: float | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    status: SetupStatus = SetupStatus.IDEA
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PaperOrder(BaseModel):
    order_id: str = Field(default_factory=lambda: f"paper_order_{uuid4().hex}")
    label: str = "PAPER"
    portfolio_id: str
    setup_id: str | None = None
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    requested_price: float | None = None  # limit/stop trigger price; None for market
    fill_price: float | None = None
    slippage_assumption_bps: float = 5.0
    fee_assumption_bps: float = 2.0
    fees_paid: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = Field(default_factory=utc_now)
    filled_at: datetime | None = None
    rejection_reason: str | None = None


class TradeResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"journal_{uuid4().hex}")
    label: str = "PAPER"
    setup_id: str | None = None
    thesis_id: str | None = None
    portfolio_id: str
    symbol: str
    direction: TradeDirection
    entry_price: float | None = None
    entry_time: datetime | None = None
    exit_price: float | None = None
    exit_time: datetime | None = None
    risk_amount: float | None = None
    result: TradeResult = TradeResult.OPEN
    pnl: float | None = None
    duration_seconds: float | None = None
    models_involved: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    mistakes: list[str] = Field(default_factory=list)
    what_worked: list[str] = Field(default_factory=list)
    lesson: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
