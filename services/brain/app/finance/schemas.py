from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstrumentType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"


class Instrument(BaseModel):
    symbol: str
    name: str | None = None
    type: InstrumentType = InstrumentType.EQUITY
    exchange: str | None = None
    currency: str = "USD"
    sector: str | None = None
    industry: str | None = None
    timezone: str = "UTC"
    provider_ids: list[str] = Field(default_factory=list)

    def normalized_symbol(self) -> str:
        return self.symbol.upper()


class WatchlistItem(BaseModel):
    instrument: Instrument
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    added_at: datetime = Field(default_factory=utc_now)
    alerts: list[str] = Field(default_factory=list)
    notes: str | None = None
    thesis: str | None = None


class Watchlist(BaseModel):
    id: str = Field(default_factory=lambda: f"watchlist_{uuid4().hex}")
    name: str
    items: list[WatchlistItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def add(self, item: WatchlistItem) -> None:
        existing = self.find(item.instrument.normalized_symbol())
        if existing is not None:
            self.items.remove(existing)
        self.items.append(item)
        self.updated_at = utc_now()

    def find(self, symbol: str) -> WatchlistItem | None:
        normalized = symbol.upper()
        return next((item for item in self.items if item.instrument.normalized_symbol() == normalized), None)

    def remove(self, symbol: str) -> bool:
        item = self.find(symbol)
        if item is None:
            return False
        self.items.remove(item)
        self.updated_at = utc_now()
        return True


class PortfolioKind(str, Enum):
    MANUAL = "manual"   # manually entered real portfolio for analytics only
    PAPER = "paper"      # simulated paper portfolio


class Position(BaseModel):
    instrument: Instrument
    quantity: float
    average_price: float
    current_price: float | None = None
    opened_at: datetime = Field(default_factory=utc_now)

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_price

    @property
    def market_value(self) -> float | None:
        if self.current_price is None:
            return None
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float | None:
        market_value = self.market_value
        if market_value is None:
            return None
        return market_value - self.cost_basis


class Portfolio(BaseModel):
    id: str = Field(default_factory=lambda: f"portfolio_{uuid4().hex}")
    name: str
    kind: PortfolioKind = PortfolioKind.MANUAL
    base_currency: str = "USD"
    cash: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    realized_pnl: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def find_position(self, symbol: str) -> Position | None:
        normalized = symbol.upper()
        return next((position for position in self.positions if position.instrument.normalized_symbol() == normalized), None)

    def total_unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl or 0.0 for position in self.positions)

    def total_market_value(self) -> float:
        return sum(position.market_value or position.cost_basis for position in self.positions)

    def total_value(self) -> float:
        return self.cash + self.total_market_value()
