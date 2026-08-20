from __future__ import annotations

from .cache import TTLCache
from .registry import ProviderRegistry
from .schemas import Fundamentals


class FundamentalsService:
    def __init__(self, registry: ProviderRegistry, ttl_seconds: float = 86400.0):
        self.registry = registry
        self.cache: TTLCache[Fundamentals] = TTLCache(ttl_seconds)

    async def get_fundamentals(self, symbol: str, *, provider_id: str | None = None) -> Fundamentals:
        cache_key = f"{provider_id or 'default'}:{symbol.upper()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        provider = self.registry.get(provider_id) if provider_id else self.registry.default()
        fundamentals = await provider.get_fundamentals(symbol)
        self.cache.set(cache_key, fundamentals)
        return fundamentals
