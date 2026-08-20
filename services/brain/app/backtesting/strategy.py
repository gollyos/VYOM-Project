from __future__ import annotations

from app.market_data.schemas import Candle
from app.strategies.schemas import StrategySpec


class StrategyValidationError(ValueError):
    pass


def validate_for_backtest(spec: StrategySpec, candles: list[Candle], *, max_bars: int) -> None:
    """Fails closed rather than silently running a malformed or
    under-specified backtest (rule 24/26)."""
    problems = spec.validate_structure()
    if problems:
        raise StrategyValidationError("; ".join(problems))
    if len(candles) < 30:
        raise StrategyValidationError(f"Only {len(candles)} bar(s) of history available; at least 30 are required for a meaningful backtest")
    if len(candles) > max_bars:
        raise StrategyValidationError(f"{len(candles)} bars exceeds max_bars_per_backtest ({max_bars})")
