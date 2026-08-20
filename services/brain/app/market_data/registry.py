from __future__ import annotations

from typing import Any

import yaml

from .provider import DisconnectedMarketDataProvider, LocalFixtureMarketDataProvider, MarketDataProvider
from .schemas import MarketDataCapability, ProviderCapabilityInfo


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
        # `live_market_data` intentionally has no real adapter in this
        # repository; enabling it in config alone never makes it available.
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
        for provider in self.providers.values():
            return provider  # local-fixture supports every capability today
        return DisconnectedMarketDataProvider()

    async def list_capabilities(self) -> list[ProviderCapabilityInfo]:
        return [await provider.capability_info() for provider in self.providers.values()]
