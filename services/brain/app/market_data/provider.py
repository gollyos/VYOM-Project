from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from .schemas import (
    Candle,
    CandleSeries,
    DataFreshness,
    Fundamentals,
    MarketDataCapability,
    MarketState,
    MarketStatus,
    MarketType,
    ProviderCapabilityInfo,
    ProviderStatus,
    Quote,
    utc_now,
)


class MarketDataProvider(ABC):
    """Provider-independent market-data interface (rule 1). No provider is
    hardcoded as *the* source — callers go through `ProviderRegistry`."""

    provider_id: str = "unknown"

    @abstractmethod
    async def capability_info(self) -> ProviderCapabilityInfo: ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: str, lookback: int) -> CandleSeries: ...

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> Fundamentals: ...

    @abstractmethod
    async def get_market_status(self, market: MarketType) -> MarketStatus: ...


class DisconnectedMarketDataProvider(MarketDataProvider):
    """Honest default: no live market-data provider is configured. Never
    invents a value — every method fails closed, matching the Phase 7/8
    integration-honesty pattern."""

    provider_id = "disconnected"

    async def capability_info(self) -> ProviderCapabilityInfo:
        return ProviderCapabilityInfo(provider_id=self.provider_id, status=ProviderStatus.UNAVAILABLE)

    async def get_quote(self, symbol: str) -> Quote:
        raise RuntimeError("No market-data provider is configured")

    async def get_candles(self, symbol: str, timeframe: str, lookback: int) -> CandleSeries:
        raise RuntimeError("No market-data provider is configured")

    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        raise RuntimeError("No market-data provider is configured")

    async def get_market_status(self, market: MarketType) -> MarketStatus:
        raise RuntimeError("No market-data provider is configured")


class LocalFixtureMarketDataProvider(MarketDataProvider):
    """Deterministic, offline, always-available fixture provider. Every
    value is explicitly labeled `freshness=MOCK` and `provider=local-fixture`
    so it can never be mistaken for a live quote (rule 2). Values are a
    reproducible pseudo-random walk seeded from the symbol so the same
    symbol always yields the same series — required for repeatable tests
    and demos without paid credentials."""

    provider_id = "local-fixture"

    def _seed(self, symbol: str) -> int:
        return int(hashlib.sha256(symbol.upper().encode("utf-8")).hexdigest()[:8], 16)

    def _base_price(self, symbol: str) -> float:
        seed = self._seed(symbol)
        return 10.0 + (seed % 4900) / 10.0  # 10.00 - 500.00

    def _walk(self, symbol: str, count: int) -> list[float]:
        seed = self._seed(symbol)
        price = self._base_price(symbol)
        prices: list[float] = []
        state = seed
        for step in range(count):
            state = (state * 1103515245 + 12345 + step) & 0x7FFFFFFF
            delta_pct = ((state % 2001) - 1000) / 100000.0  # +/- 1%
            price = max(0.5, price * (1 + delta_pct + 0.0002 * math.sin(step / 7.0)))
            prices.append(round(price, 4))
        return prices

    async def capability_info(self) -> ProviderCapabilityInfo:
        return ProviderCapabilityInfo(
            provider_id=self.provider_id,
            capabilities=list(MarketDataCapability),
            markets_supported=[MarketType.US_EQUITY, MarketType.CRYPTO, MarketType.FOREX, MarketType.INDEX],
            status=ProviderStatus.AVAILABLE,
            rate_limits={"requests_per_minute": 1000},
            freshness=DataFreshness.MOCK,
            cost_policy="free",
        )

    async def get_quote(self, symbol: str) -> Quote:
        prices = self._walk(symbol, 2)
        previous_close, price = prices[0], prices[1]
        change = round(price - previous_close, 4)
        return Quote(
            symbol=symbol.upper(),
            provider=self.provider_id,
            timestamp=utc_now(),
            retrieved_at=utc_now(),
            freshness=DataFreshness.MOCK,
            market_state=MarketState.OPEN,
            price=price,
            bid=round(price - 0.01, 4),
            ask=round(price + 0.01, 4),
            day_open=previous_close,
            day_high=round(max(previous_close, price) * 1.004, 4),
            day_low=round(min(previous_close, price) * 0.996, 4),
            previous_close=previous_close,
            volume=float(1_000_000 + (self._seed(symbol) % 5_000_000)),
            change=change,
            change_pct=round((change / previous_close) * 100, 3) if previous_close else 0.0,
        )

    async def get_candles(self, symbol: str, timeframe: str, lookback: int) -> CandleSeries:
        lookback = max(1, min(lookback, 2000))
        closes = self._walk(symbol, lookback)
        now = utc_now()
        step = _timeframe_delta(timeframe)
        candles: list[Candle] = []
        for index, close in enumerate(closes):
            ts = now - step * (lookback - index)
            open_price = closes[index - 1] if index > 0 else close
            high = round(max(open_price, close) * 1.003, 4)
            low = round(min(open_price, close) * 0.997, 4)
            volume = float(500_000 + ((self._seed(symbol) + index * 97) % 2_000_000))
            candles.append(Candle(timestamp=ts, open=open_price, high=high, low=low, close=close, volume=volume))
        return CandleSeries(
            symbol=symbol.upper(), provider=self.provider_id, timestamp=now, retrieved_at=now,
            freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, timeframe=timeframe, candles=candles,
        )

    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        seed = self._seed(symbol)
        sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer Discretionary", "Industrials"]
        return Fundamentals(
            symbol=symbol.upper(), provider=self.provider_id, timestamp=utc_now(), retrieved_at=utc_now(),
            freshness=DataFreshness.MOCK, market_state=MarketState.UNKNOWN,
            name=f"{symbol.upper()} Fixture Corp", sector=sectors[seed % len(sectors)],
            industry="Diversified", market_cap=float(1_000_000_000 + (seed % 900_000_000_000)),
            pe_ratio=round(8 + (seed % 400) / 10.0, 2), eps=round(0.5 + (seed % 1500) / 100.0, 2),
            dividend_yield=round((seed % 400) / 100.0, 2),
            description="Deterministic local-fixture fundamentals for offline analysis and tests.",
        )

    async def get_market_status(self, market: MarketType) -> MarketStatus:
        return MarketStatus(market=market, state=MarketState.OPEN, provider=self.provider_id, checked_at=utc_now(), freshness=DataFreshness.MOCK)


def _timeframe_delta(timeframe: str) -> timedelta:
    mapping = {
        "1m": timedelta(minutes=1), "5m": timedelta(minutes=5), "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1), "1w": timedelta(weeks=1),
    }
    return mapping.get(timeframe, timedelta(days=1))
