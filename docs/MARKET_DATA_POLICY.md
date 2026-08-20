# VYOM Market Data Policy

## Provider-independent abstraction

`MarketDataProvider` (`services/brain/app/market_data/provider.py`) is an
abstract interface — no provider is hardcoded as *the* data source.
Capabilities are typed (`MarketDataCapability`): `quotes`, `candles`,
`historical_prices`, `fundamentals`, `company_metadata`, `indices`,
`crypto`, `forex`, `market_status`. Every provider publishes
`provider_id`, `capabilities`, `markets_supported`, `status`,
`rate_limits`, `freshness`, and `cost_policy` through
`capability_info()`.

`ProviderRegistry` (`services/brain/app/market_data/registry.py`) resolves
a provider by capability, then by the configured default
(`config/market_data.yaml`), then falls back to an honest
`DisconnectedMarketDataProvider` that fails closed rather than inventing a
value.

## The local-fixture default

`LocalFixtureMarketDataProvider` is enabled by default so quotes,
candles, and fundamentals work offline and in tests without a paid
subscription — matching the Phase 7/8 integration-honesty pattern. Every
value it returns is a reproducible pseudo-random walk seeded from the
symbol (same symbol -> same series) and is always labeled
`freshness=MOCK`, `provider=local-fixture`. It is never presented as a
live quote.

A real live-data adapter can be added later behind the same
`MarketDataProvider` interface; `config/market_data.yaml` already reserves
a `live_market_data` entry, but it has no working adapter or credentials
in this repository — enabling the config flag alone does not make it
available.

## Data freshness

Every market-data object is a `MarketDataEnvelope`: `symbol`, `provider`,
`timestamp`, `retrieved_at`, `freshness`, `market_state`. `DataFreshness`
is one of `live`, `delayed`, `cached`, `historical`, `mock` — these are
never used interchangeably. `FreshnessPolicy`
(`services/brain/app/market_data/freshness.py`) classifies freshness from
age against `config/market_data.yaml` windows
(`live_max_age_seconds`/`delayed_max_age_seconds`/`cached_max_age_seconds`);
anything older becomes `historical`. A value from a mock/local-fixture
provider is always `mock`, regardless of age.

`FreshnessPolicy.is_stale_for_decision()` is the explicit check a
consequential workflow (paper order placement, risk evaluation) must call
before acting on data — data older than the configured
`max_stale_seconds_before_pause` must pause dependent automation rather
than act on it (rule 54, `docs/TRADING_RISK_POLICY.md`).

## Caching

`TTLCache` (`services/brain/app/market_data/cache.py`) avoids
re-downloading identical historical ranges/quotes within a short TTL
(`config/market_data.yaml`: `cache.*_ttl_seconds`). Caching never
overrides `FreshnessPolicy` — a cached value still carries its true
`retrieved_at` timestamp and is labeled `cached`, not `live`.

## Failure handling

If a required provider is unavailable or its data exceeds the configured
staleness window, the caller receives an explicit unavailable/stale
result — never invented values. Dependent paper-trading automation must
detect this and pause rather than trade on stale data (rule 54).
