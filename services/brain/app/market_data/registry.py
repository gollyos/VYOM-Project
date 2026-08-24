from __future__ import annotations

from typing import Any

import yaml

from .provider import DisconnectedMarketDataProvider, LocalFixtureMarketDataProvider, MarketDataProvider
from .schemas import MarketDataCapability, ProviderCapabilityInfo
from .yahoo_provider import YahooFinanceProvider


class ProviderRegistry:
    """Registry of provider-independent market-data sources (rule 1). No
    single provider is hardcoded as *the* data source; callers resolve a
    provider by capability, falling back to the configured default, and
    finally to an honest `DisconnectedMarketDataProvider`."""

    def __init__(self, providers: dict[str, MarketDataProvider], default_provider_id: str | None = None):
        self.providers = providers
        self.default_provider_id = default_provider_id

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ProviderRegistry":
        providers: dict[str, MarketDataProvider] = {}
        provider_config = config.get("providers", {})
        if provider_config.get("local_fixture", {}).get("enabled", True):
            providers["local-fixture"] = LocalFixtureMarketDataProvider()
        # Real, free, unauthenticated Yahoo Finance adapter — see
        # app/market_data/yahoo_provider.py's docstring for the freshness
        # discipline (DELAYED, never LIVE) this provider maintains.
        if provider_config.get("live_market_data", {}).get("enabled", False):
            providers["yahoo-finance"] = YahooFinanceProvider()
        default_id = config.get("default_provider", "local-fixture")
        return cls(providers, default_provider_id=default_id)

    @staticmethod
    def load_config(path) -> dict[str, Any]:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def get(self, provider_id: str) -> MarketDataProvider | None:
        return self.providers.get(provider_id)

    def default(self) -> MarketDataProvider:
        if self.default_provider_id and self.default_provider_id in self.providers:
            return self.providers[self.default_provider_id]
        if self.providers:
            return next(iter(self.providers.values()))
        return DisconnectedMarketDataProvider()

    def resolve(self, capability: MarketDataCapability | None = None) -> MarketDataProvider:
        """Return a provider supporting `capability`, else the default,
        else an honest disconnected provider. Never silently substitutes a
        provider that cannot actually serve the requested capability type."""
        if capability is None:
            return self.default()
        default = self.default()
        # Prefer the configured default when it exists and can plausibly
        # serve every capability this repo defines (both current providers
        # can) — this keeps existing default-provider behaviour unchanged
        # now that a second provider exists, rather than picking whichever
        # provider `dict` iteration happens to yield first.
        if default is not None and not isinstance(default, DisconnectedMarketDataProvider):
            return default
        for provider in self.providers.values():
            return provider
        return DisconnectedMarketDataProvider()

    async def list_capabilities(self) -> list[ProviderCapabilityInfo]:
        return [await provider.capability_info() for provider in self.providers.values()]
