"""Tests for YahooFinanceProvider — real market-data integration added this
session, using httpx.MockTransport against realistically-shaped Yahoo
Finance API responses (same pattern as test_google_workspace_integrations.py)
rather than a live network call, so these run offline and deterministically.
"""
from __future__ import annotations

import httpx
import pytest

from app.market_data.provider import DisconnectedMarketDataProvider, LocalFixtureMarketDataProvider
from app.market_data.registry import ProviderRegistry
from app.market_data.schemas import DataFreshness, MarketState, MarketType
from app.market_data.yahoo_provider import YahooFinanceProvider, _market_state_from_recency


def _chart_response(price: float = 150.0, previous_close: float = 148.0) -> dict:
    return {
        "chart": {
            "result": [{
                "meta": {
                    "currency": "USD", "symbol": "TEST", "regularMarketPrice": price,
                    "chartPreviousClose": previous_close, "regularMarketDayHigh": price + 2,
                    "regularMarketDayLow": price - 2, "regularMarketVolume": 1_000_000,
                    "regularMarketTime": 9_999_999_999,  # far future -> "recent" in any test run
                },
                "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
                "indicators": {
                    "quote": [{
                        "open": [147.0, 148.5, 149.0],
                        "high": [149.0, 150.0, 151.0],
                        "low": [146.0, 147.5, 148.5],
                        "close": [148.0, 149.5, price],
                        "volume": [900000, 950000, 1000000],
                    }]
                },
            }],
            "error": None,
        }
    }


@pytest.mark.asyncio
async def test_get_quote_parses_real_shaped_chart_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chart_response(price=310.34, previous_close=305.59))

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    quote = await provider.get_quote("AAPL")

    assert quote.symbol == "AAPL"
    assert quote.price == 310.34
    assert quote.previous_close == 305.59
    assert quote.change == pytest.approx(4.75, abs=0.01)
    assert quote.freshness == DataFreshness.DELAYED  # NEVER "live" — see docs/MARKET_DATA_POLICY.md
    assert quote.provider == "yahoo-finance"
    await provider.aclose()


@pytest.mark.asyncio
async def test_get_candles_parses_ohlcv_series():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chart_response())

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    series = await provider.get_candles("AAPL", "1d", 10)

    assert len(series.candles) == 3
    assert series.candles[-1].close == 150.0
    assert series.candles[0].open == 147.0
    assert series.freshness == DataFreshness.DELAYED
    await provider.aclose()


@pytest.mark.asyncio
async def test_get_quote_raises_on_yahoo_error_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"chart": {"result": None, "error": {"description": "Not Found"}}})

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="Not Found|no data"):
        await provider.get_quote("NOTASYMBOL")
    await provider.aclose()


@pytest.mark.asyncio
async def test_get_fundamentals_fetches_crumb_then_quote_summary():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        calls.append(path)
        if "fc.yahoo.com" in path:
            return httpx.Response(200, text="")
        if "getcrumb" in path:
            return httpx.Response(200, text="abc123crumb")
        if "quoteSummary" in path:
            assert "crumb=abc123crumb" in path
            return httpx.Response(200, json={
                "quoteSummary": {"result": [{
                    "assetProfile": {"sector": "Technology", "industry": "Consumer Electronics", "longBusinessSummary": "Makes phones."},
                    "summaryDetail": {"trailingPE": {"raw": 35.5}, "dividendYield": {"raw": 0.005}},
                    "defaultKeyStatistics": {"trailingEps": {"raw": 6.1}},
                    "price": {"longName": "Apple Inc.", "marketCap": {"raw": 3_000_000_000_000}, "marketState": "POST"},
                }]}
            })
        return httpx.Response(404)

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fundamentals = await provider.get_fundamentals("AAPL")

    assert fundamentals.name == "Apple Inc."
    assert fundamentals.sector == "Technology"
    assert fundamentals.pe_ratio == 35.5
    assert fundamentals.market_state == MarketState.AFTER_HOURS
    assert any("getcrumb" in c for c in calls)  # the crumb handshake actually happened
    await provider.aclose()


def test_market_state_from_recency_open_vs_closed():
    import time

    recent = {"regularMarketTime": time.time() - 30}
    stale = {"regularMarketTime": time.time() - 86400}
    missing = {}
    assert _market_state_from_recency(recent) == MarketState.OPEN
    assert _market_state_from_recency(stale) == MarketState.CLOSED
    assert _market_state_from_recency(missing) == MarketState.UNKNOWN


@pytest.mark.asyncio
async def test_capability_info_never_claims_live_freshness():
    provider = YahooFinanceProvider()
    info = await provider.capability_info()
    assert info.freshness == DataFreshness.DELAYED  # this provider must NEVER claim LIVE
    assert info.cost_policy == "free"


def test_provider_registry_wires_yahoo_when_enabled():
    config = {
        "providers": {
            "local_fixture": {"enabled": True},
            "live_market_data": {"enabled": True},
        },
        "default_provider": "local-fixture",
    }
    registry = ProviderRegistry.from_config(config)
    assert "local-fixture" in registry.providers
    assert "yahoo-finance" in registry.providers
    assert isinstance(registry.providers["local-fixture"], LocalFixtureMarketDataProvider)
    assert isinstance(registry.providers["yahoo-finance"], YahooFinanceProvider)
    # default_provider is still honoured — local-fixture stays the default
    # even with a real provider present, matching existing offline-first behaviour.
    assert isinstance(registry.default(), LocalFixtureMarketDataProvider)


def test_provider_registry_yahoo_disabled_by_default_config_flag():
    config = {"providers": {"local_fixture": {"enabled": True}, "live_market_data": {"enabled": False}}}
    registry = ProviderRegistry.from_config(config)
    assert "yahoo-finance" not in registry.providers


def test_provider_registry_resolve_never_substitutes_disconnected_when_default_exists():
    config = {"providers": {"local_fixture": {"enabled": True}}}
    registry = ProviderRegistry.from_config(config)
    from app.market_data.schemas import MarketDataCapability

    resolved = registry.resolve(MarketDataCapability.QUOTES)
    assert not isinstance(resolved, DisconnectedMarketDataProvider)
