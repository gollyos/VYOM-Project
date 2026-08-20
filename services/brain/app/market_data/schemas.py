from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketDataCapability(str, Enum):
    QUOTES = "quotes"
    CANDLES = "candles"
    HISTORICAL_PRICES = "historical_prices"
    FUNDAMENTALS = "fundamentals"
    COMPANY_METADATA = "company_metadata"
    INDICES = "indices"
    CRYPTO = "crypto"
    FOREX = "forex"
    MARKET_STATUS = "market_status"


class MarketType(str, Enum):
    US_EQUITY = "US_EQUITY"
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"


class ProviderStatus(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class DataFreshness(str, Enum):
    """How current a market-data value is. Never presented interchangeably —
    a `cached`/`historical` value must never be shown as `live`."""

    LIVE = "live"
    DELAYED = "delayed"
    CACHED = "cached"
    HISTORICAL = "historical"
    MOCK = "mock"


class MarketState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"
    UNKNOWN = "unknown"


class ProviderCapabilityInfo(BaseModel):
    provider_id: str
    capabilities: list[MarketDataCapability] = Field(default_factory=list)
    markets_supported: list[MarketType] = Field(default_factory=list)
    status: ProviderStatus = ProviderStatus.UNAVAILABLE
    rate_limits: dict[str, int] = Field(default_factory=dict)
    freshness: DataFreshness = DataFreshness.MOCK
    cost_policy: str = "unknown"


class MarketDataEnvelope(BaseModel):
    """Every market-data object carries this provenance so stale/cached data
    can never be mistaken for live data (docs/MARKET_DATA_POLICY.md)."""

    symbol: str
    provider: str
    timestamp: datetime = Field(default_factory=utc_now)
    retrieved_at: datetime = Field(default_factory=utc_now)
    freshness: DataFreshness = DataFreshness.MOCK
    market_state: MarketState = MarketState.UNKNOWN


class Quote(MarketDataEnvelope):
    price: float
    bid: float | None = None
    ask: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    change: float | None = None
    change_pct: float | None = None
    currency: str = "USD"


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class CandleSeries(MarketDataEnvelope):
    timeframe: str = "1d"
    candles: list[Candle] = Field(default_factory=list)


class Fundamentals(MarketDataEnvelope):
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    eps: float | None = None
    dividend_yield: float | None = None
    description: str | None = None


class MarketStatus(BaseModel):
    market: MarketType
    state: MarketState
    provider: str
    checked_at: datetime = Field(default_factory=utc_now)
    freshness: DataFreshness = DataFreshness.MOCK
