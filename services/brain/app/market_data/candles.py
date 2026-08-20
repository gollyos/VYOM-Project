from __future__ import annotations

from .cache import TTLCache
from .registry import ProviderRegistry
from .schemas import CandleSeries


class CandleService:
    def __init__(self, registry: ProviderRegistry, ttl_seconds: float = 3600.0):
        self.registry = registry
        self.cache: TTLCache[CandleSeries] = TTLCache(ttl_seconds)

    async def get_candles(self, symbol: str, timeframe: str = "1d", lookback: int = 90, *, provider_id: str | None = None) -> CandleSeries:
        cache_key = f"{provider_id or 'default'}:{symbol.upper()}:{timeframe}:{lookback}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        provider = self.registry.get(provider_id) if provider_id else self.registry.default()
        series = await provider.get_candles(symbol, timeframe, lookback)
        self.cache.set(cache_key, series)
        return series
