from __future__ import annotations

from pydantic import BaseModel, Field

from app.market_data.candles import CandleService
from app.strategies.schemas import StrategySpec

from .engine import BacktestEngine, BacktestResult


class WalkForwardResult(BaseModel):
    development: BacktestResult
    validation: BacktestResult
    out_of_sample: BacktestResult
    overfitting_flag: bool
    notes: list[str] = Field(default_factory=list)


class WalkForwardEvaluator:
    """Basic walk-forward foundation (rule 28): split history into
    development / validation / out-of-sample ranges so a strategy is never
    judged on the exact same data it was tuned against (rule 27). This
    deliberately stays simple — no parameter-optimization search loop."""

    def __init__(self, engine: BacktestEngine, candle_service: CandleService):
        self.engine = engine
        self.candle_service = candle_service

    async def evaluate(
        self,
        spec: StrategySpec,
        symbol: str,
        *,
        timeframe: str | None = None,
        lookback: int = 600,
        development_fraction: float = 0.5,
        validation_fraction: float = 0.25,
        initial_capital: float = 100_000.0,
        fees_bps: float = 2.0,
        slippage_bps: float = 5.0,
    ) -> WalkForwardResult:
        timeframe = timeframe or spec.timeframe
        series = await self.candle_service.get_candles(symbol, timeframe, lookback)
        candles = series.candles
        total = len(candles)
        dev_end = int(total * development_fraction)
        val_end = dev_end + int(total * validation_fraction)

        splits = {
            "development": candles[:dev_end],
            "validation": candles[dev_end:val_end],
            "out_of_sample": candles[val_end:],
        }
        results: dict[str, BacktestResult] = {}
        for name, chunk in splits.items():
            results[name] = self.engine.run_on_candles(
                spec, symbol, chunk, provider=series.provider, freshness=series.freshness.value,
                initial_capital=initial_capital, fees_bps=fees_bps, slippage_bps=slippage_bps, timeframe=timeframe,
            )

        dev_return = results["development"].metrics.total_return_pct or 0.0
        oos_return = results["out_of_sample"].metrics.total_return_pct or 0.0
        overfitting_flag = dev_return > 0 and oos_return < dev_return * 0.25
        notes = [
            f"Development return {dev_return:.2f}% vs out-of-sample return {oos_return:.2f}%.",
        ]
        if overfitting_flag:
            notes.append("Out-of-sample performance is far weaker than development performance; treat this strategy as possibly overfit.")

        return WalkForwardResult(
            development=results["development"], validation=results["validation"], out_of_sample=results["out_of_sample"],
            overfitting_flag=overfitting_flag, notes=notes,
        )
