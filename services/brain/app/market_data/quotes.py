from __future__ import annotations

from .cache import TTLCache
from .freshness import FreshnessPolicy
from .registry import ProviderRegistry
from .schemas import Quote


class QuoteService:
    def __init__(self, registry: ProviderRegistry, freshness_policy: FreshnessPolicy, ttl_seconds: float = 5.0):
        self.registry = registry
        self.freshness_policy = freshness_policy
        self.cache: TTLCache[Quote] = TTLCache(ttl_seconds)

    async def get_quote(self, symbol: str, *, provider_id: str | None = None) -> Quote:
        cache_key = f"{provider_id or 'default'}:{symbol.upper()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        provider = self.registry.get(provider_id) if provider_id else self.registry.default()
        quote = await provider.get_quote(symbol)
        self.cache.set(cache_key, quote)
        return quote
