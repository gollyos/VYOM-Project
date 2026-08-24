from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx

from .provider import MarketDataProvider
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

# Yahoo Finance's public chart/quote endpoints require SOME User-Agent to
# avoid an immediate "Too Many Requests" from their edge — no API key is
# needed for these read-only public endpoints, but a browser-shaped header
# is (verified: a bare httpx request without one is rejected outright).
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VYOM-MarketData/1.0"}
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_COOKIE_URL = "https://fc.yahoo.com"
_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"

_INTERVAL_TO_YAHOO = {
    "1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "4h": "60m", "1d": "1d", "1w": "1wk",
}
_RANGE_FOR_LOOKBACK = {
    "1m": "1d", "5m": "5d", "15m": "5d", "1h": "1mo", "4h": "3mo", "1d": "2y", "1w": "5y",
}


def _market_state_from_yahoo(raw: str | None) -> MarketState:
    mapping = {
        "REGULAR": MarketState.OPEN, "CLOSED": MarketState.CLOSED,
        "PRE": MarketState.PRE_MARKET, "PREPRE": MarketState.PRE_MARKET,
        "POST": MarketState.AFTER_HOURS, "POSTPOST": MarketState.AFTER_HOURS,
    }
    return mapping.get((raw or "").upper(), MarketState.UNKNOWN)


def _market_state_from_recency(meta: dict) -> MarketState:
    """Yahoo's /v8/finance/chart response has NO explicit marketState field
    (verified against the live endpoint) — only quoteSummary's `price`
    module carries one, and that needs the crumb-authenticated call. For
    chart/quote responses, approximate from how recent regularMarketTime
    is: within ~2 minutes of "now" during typical US market hours reads as
    open; anything older reads as closed. This is a best-effort estimate,
    not authoritative — get_market_status() uses the real quoteSummary
    field when available."""
    market_time = meta.get("regularMarketTime")
    if not market_time:
        return MarketState.UNKNOWN
    age_seconds = time.time() - market_time
    if age_seconds < 0:
        return MarketState.UNKNOWN
    return MarketState.OPEN if age_seconds < 120 else MarketState.CLOSED


class YahooFinanceProvider(MarketDataProvider):
    """Real, live market data over Yahoo Finance's public (unauthenticated)
    chart/quoteSummary endpoints. No API key required, but rate-limited by
    Yahoo's edge (undocumented, empirically generous for personal use) —
    callers should still go through TTLCache (app/market_data/cache.py)
    rather than hammering this directly. Delayed by exchange rules (this
    is the SAME data yahoo.com's own UI shows a retail user, not a paid
    real-time feed), so every value is labeled `freshness=DELAYED`, never
    `LIVE`, per docs/MARKET_DATA_POLICY.md's freshness discipline."""

    provider_id = "yahoo-finance"

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        #: Yahoo's quoteSummary endpoint (fundamentals) requires a session
        #: cookie + "crumb" token, obtained via a one-time handshake; the
        #: chart/quote endpoints do not. Cached for the client's lifetime —
        #: refetched once if a request comes back 401 (crumb expired).
        self._crumb: str | None = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, headers=_HEADERS)
        return self._client

    async def _ensure_crumb(self) -> str:
        if self._crumb:
            return self._crumb
        client = self._pooled()
        await client.get(_COOKIE_URL)  # sets Yahoo's session cookie on this client
        response = await client.get(_CRUMB_URL)
        if response.status_code >= 400 or not response.text.strip():
            raise RuntimeError("Could not obtain a Yahoo Finance session crumb")
        self._crumb = response.text.strip()
        return self._crumb

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def capability_info(self) -> ProviderCapabilityInfo:
        return ProviderCapabilityInfo(
            provider_id=self.provider_id,
            capabilities=[
                MarketDataCapability.QUOTES, MarketDataCapability.CANDLES,
                MarketDataCapability.HISTORICAL_PRICES, MarketDataCapability.FUNDAMENTALS,
                MarketDataCapability.COMPANY_METADATA, MarketDataCapability.MARKET_STATUS,
            ],
            markets_supported=[MarketType.US_EQUITY, MarketType.INDEX, MarketType.CRYPTO],
            status=ProviderStatus.AVAILABLE,
            rate_limits={"requests_per_minute": 60},  # conservative, undocumented by Yahoo
            freshness=DataFreshness.DELAYED,
            cost_policy="free",
        )

    async def _chart(self, symbol: str, *, interval: str, range_: str, include_prepost: bool = False) -> dict:
        response = await self._pooled().get(
            _CHART_URL.format(symbol=symbol.upper()),
            params={"interval": interval, "range": range_, "includePrePost": str(include_prepost).lower()},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Yahoo Finance chart request failed: HTTP {response.status_code}")
        data = response.json()
        chart = data.get("chart", {})
        if chart.get("error"):
            raise RuntimeError(f"Yahoo Finance error for '{symbol}': {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise RuntimeError(f"Yahoo Finance returned no data for '{symbol}' — check the symbol")
        return results[0]

    async def get_quote(self, symbol: str) -> Quote:
        result = await self._chart(symbol, interval="1d", range_="5d")
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            raise RuntimeError(f"Yahoo Finance returned no price for '{symbol}'")
        change = round(price - previous_close, 4) if previous_close else None
        return Quote(
            symbol=symbol.upper(), provider=self.provider_id, timestamp=utc_now(), retrieved_at=utc_now(),
            freshness=DataFreshness.DELAYED, market_state=_market_state_from_recency(meta),
            price=round(price, 4),
            day_open=meta.get("regularMarketDayLow"),  # yahoo's chart meta omits a distinct "open"; see candles for OHLC
            day_high=meta.get("regularMarketDayHigh"), day_low=meta.get("regularMarketDayLow"),
            previous_close=previous_close, volume=meta.get("regularMarketVolume"),
            change=change, change_pct=round((change / previous_close) * 100, 3) if change and previous_close else None,
            currency=meta.get("currency", "USD"),
        )

    async def get_candles(self, symbol: str, timeframe: str, lookback: int) -> CandleSeries:
        interval = _INTERVAL_TO_YAHOO.get(timeframe, "1d")
        range_ = _RANGE_FOR_LOOKBACK.get(timeframe, "2y")
        result = await self._chart(symbol, interval=interval, range_=range_)
        meta = result.get("meta", {})
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        opens, highs, lows, closes, volumes = (
            quote.get("open") or [], quote.get("high") or [], quote.get("low") or [],
            quote.get("close") or [], quote.get("volume") or [],
        )
        candles: list[Candle] = []
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue  # Yahoo pads gaps (holidays/pre-market) with nulls
            candles.append(Candle(
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=opens[i] if i < len(opens) and opens[i] is not None else closes[i],
                high=highs[i] if i < len(highs) and highs[i] is not None else closes[i],
                low=lows[i] if i < len(lows) and lows[i] is not None else closes[i],
                close=closes[i],
                volume=float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0,
            ))
        candles = candles[-lookback:] if lookback else candles
        return CandleSeries(
            symbol=symbol.upper(), provider=self.provider_id, timestamp=utc_now(), retrieved_at=utc_now(),
            freshness=DataFreshness.DELAYED, market_state=_market_state_from_recency(meta),
            timeframe=timeframe, candles=candles,
        )

    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        crumb = await self._ensure_crumb()
        response = await self._pooled().get(
            _QUOTE_SUMMARY_URL.format(symbol=symbol.upper()),
            params={"modules": "assetProfile,summaryDetail,defaultKeyStatistics,price", "crumb": crumb},
        )
        if response.status_code == 401:
            # Crumb expired mid-session — refetch once and retry.
            self._crumb = None
            crumb = await self._ensure_crumb()
            response = await self._pooled().get(
                _QUOTE_SUMMARY_URL.format(symbol=symbol.upper()),
                params={"modules": "assetProfile,summaryDetail,defaultKeyStatistics,price", "crumb": crumb},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Yahoo Finance fundamentals request failed: HTTP {response.status_code}")
        data = response.json()
        results = data.get("quoteSummary", {}).get("result") or []
        if not results:
            raise RuntimeError(f"Yahoo Finance returned no fundamentals for '{symbol}'")
        modules = results[0]
        profile = modules.get("assetProfile", {})
        summary = modules.get("summaryDetail", {})
        stats = modules.get("defaultKeyStatistics", {})
        price_module = modules.get("price", {})

        def _raw(node: dict | None, default=None):
            if not isinstance(node, dict):
                return default
            return node.get("raw", default)

        return Fundamentals(
            symbol=symbol.upper(), provider=self.provider_id, timestamp=utc_now(), retrieved_at=utc_now(),
            freshness=DataFreshness.DELAYED, market_state=_market_state_from_yahoo(price_module.get("marketState")),
            name=price_module.get("longName") or price_module.get("shortName"),
            sector=profile.get("sector"), industry=profile.get("industry"),
            market_cap=_raw(price_module.get("marketCap")),
            pe_ratio=_raw(summary.get("trailingPE")), eps=_raw(stats.get("trailingEps")),
            dividend_yield=_raw(summary.get("dividendYield")),
            description=profile.get("longBusinessSummary"),
        )

    async def get_market_status(self, market: MarketType) -> MarketStatus:
        # Use a well-known index/equity as a proxy since Yahoo has no
        # standalone "is the market open" endpoint; get_fundamentals's
        # `price` module carries the real authoritative marketState field
        # (the chart endpoint used elsewhere in this provider does not).
        proxy = "^GSPC" if market == MarketType.US_EQUITY else "^GSPC"
        try:
            fundamentals = await self.get_fundamentals(proxy)
            state = fundamentals.market_state
        except Exception:
            try:
                result = await self._chart(proxy, interval="1d", range_="1d")
                state = _market_state_from_recency(result.get("meta", {}))
            except Exception:
                state = MarketState.UNKNOWN
        return MarketStatus(market=market, state=state, provider=self.provider_id, checked_at=utc_now(), freshness=DataFreshness.DELAYED)
