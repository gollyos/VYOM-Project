from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TechnicalSnapshot(BaseModel):
    symbol: str
    timeframe: str
    as_of: datetime
    sample_size: int
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    rsi_14: float | None = None
    atr: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    returns_pct: float | None = None
    volatility_pct: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    support_candidates: list[float] = Field(default_factory=list)
    resistance_candidates: list[float] = Field(default_factory=list)
    insufficient_data_for: list[str] = Field(default_factory=list)


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNCERTAIN = "uncertain"


class RegimeAssessment(BaseModel):
    regime: MarketRegime
    confidence: float = Field(ge=0, le=1)
    rationale: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=utc_now)


class CatalystRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"catalyst_{uuid4().hex}")
    category: str  # earnings, product_announcement, regulatory, macro, company_announcement, industry
    description: str
    source: str
    date: datetime | None = None
    relevance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)


class SentimentAssessment(BaseModel):
    method: str = "heuristic-keyword"
    label: str  # positive, negative, neutral, mixed
    score: float = Field(ge=-1, le=1)
    sample_size: int
    rationale: str
