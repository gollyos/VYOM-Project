from __future__ import annotations

import math

from pydantic import BaseModel

from app.market_data.schemas import Candle


class VolatilityResult(BaseModel):
    daily_volatility_pct: float
    annualized_volatility_pct: float
    sample_size: int


def compute_volatility(candles: list[Candle]) -> VolatilityResult | None:
    """Sample standard deviation of daily returns. Returns None (not a
    fabricated 0) when there isn't enough history to support the metric
    (rule 6)."""
    if len(candles) < 3:
        return None
    closes = [c.close for c in candles]
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    daily_stdev = math.sqrt(variance)
    return VolatilityResult(
        daily_volatility_pct=round(daily_stdev * 100, 4),
        annualized_volatility_pct=round(daily_stdev * math.sqrt(252) * 100, 4),
        sample_size=len(returns),
    )


class DrawdownResult(BaseModel):
    max_drawdown_pct: float
    peak_value: float
    trough_value: float
    current_drawdown_pct: float


def compute_drawdown(equity_curve: list[float]) -> DrawdownResult | None:
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    max_dd = 0.0
    peak_at_max, trough_at_max = equity_curve[0], equity_curve[0]
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > max_dd:
                max_dd = drawdown
                peak_at_max, trough_at_max = peak, value
    current_peak = max(equity_curve)
    current_value = equity_curve[-1]
    current_dd = ((current_peak - current_value) / current_peak) if current_peak > 0 else 0.0
    return DrawdownResult(
        max_drawdown_pct=round(max_dd * 100, 4),
        peak_value=peak_at_max,
        trough_value=trough_at_max,
        current_drawdown_pct=round(current_dd * 100, 4),
    )
