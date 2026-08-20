from __future__ import annotations

import math

from app.market_data.schemas import Candle

from .schemas import TechnicalSnapshot, utc_now


def volatility_pct(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    daily_returns = [(values[i] / values[i - 1]) - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    if len(daily_returns) < 2:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    return round(math.sqrt(variance) * 100, 4)


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 6)


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    series = [values[0]]
    for value in values[1:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return round(ema_series(values, period)[-1], 6)


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 4)


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        current, previous = candles[i], candles[i - 1]
        true_range = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        true_ranges.append(true_range)
    window = true_ranges[-period:]
    return round(sum(window) / len(window), 6)


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float] | None:
    if len(values) < slow + signal:
        return None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_series, slow_series)]
    signal_series = ema_series(macd_line, signal)
    macd_value = macd_line[-1]
    signal_value = signal_series[-1]
    return round(macd_value, 6), round(signal_value, 6), round(macd_value - signal_value, 6)


def returns_pct(values: list[float]) -> float | None:
    if len(values) < 2 or values[0] == 0:
        return None
    return round(((values[-1] / values[0]) - 1) * 100, 4)


def support_resistance_candidates(candles: list[Candle], lookback: int = 30, top_n: int = 3) -> tuple[list[float], list[float]]:
    """Local swing-high/swing-low pivots over the recent window, deduped
    and sorted by proximity to the most recent close. Deterministic —
    never model-generated."""
    window = candles[-lookback:] if lookback else candles
    if len(window) < 5:
        return [], []
    highs, lows = [], []
    for i in range(2, len(window) - 2):
        segment = window[i - 2:i + 3]
        if window[i].high == max(c.high for c in segment):
            highs.append(round(window[i].high, 4))
        if window[i].low == min(c.low for c in segment):
            lows.append(round(window[i].low, 4))
    last_close = window[-1].close
    resistance = sorted({h for h in highs if h > last_close}, key=lambda v: v - last_close)[:top_n]
    support = sorted({l for l in lows if l < last_close}, key=lambda v: last_close - v)[:top_n]
    return support, resistance


class TechnicalAnalysisEngine:
    """All indicator computation happens here, in code — never through a
    model call (rule 8)."""

    def analyze(self, symbol: str, timeframe: str, candles: list[Candle]) -> TechnicalSnapshot:
        closes = [c.close for c in candles]
        insufficient: list[str] = []

        snapshot = TechnicalSnapshot(symbol=symbol.upper(), timeframe=timeframe, as_of=utc_now(), sample_size=len(candles))
        snapshot.sma_20 = sma(closes, 20)
        snapshot.sma_50 = sma(closes, 50)
        snapshot.sma_200 = sma(closes, 200)
        snapshot.ema_12 = ema(closes, 12)
        snapshot.ema_26 = ema(closes, 26)
        snapshot.rsi_14 = rsi(closes, 14)
        snapshot.atr = atr(candles, 14)
        macd_result = macd(closes)
        if macd_result:
            snapshot.macd, snapshot.macd_signal, snapshot.macd_histogram = macd_result
        else:
            insufficient.append("macd")
        snapshot.returns_pct = returns_pct(closes)
        snapshot.volatility_pct = volatility_pct(closes)
        if closes:
            snapshot.recent_high = round(max(closes[-30:] if len(closes) >= 30 else closes), 4)
            snapshot.recent_low = round(min(closes[-30:] if len(closes) >= 30 else closes), 4)
        support, resistance = support_resistance_candidates(candles)
        snapshot.support_candidates = support
        snapshot.resistance_candidates = resistance

        if snapshot.sma_200 is None:
            insufficient.append("sma_200")
        if snapshot.atr is None:
            insufficient.append("atr")
        if snapshot.rsi_14 is None:
            insufficient.append("rsi_14")
        snapshot.insufficient_data_for = insufficient
        return snapshot
