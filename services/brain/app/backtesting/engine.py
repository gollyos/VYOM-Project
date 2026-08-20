from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.market_data.candles import CandleService
from app.persistence.database import Database
from app.strategies.evaluator import StrategyEvaluator
from app.strategies.schemas import StrategySpec

from .metrics import BacktestMetrics, compute_metrics
from .simulator import BacktestTrade, BarSimulator, SimulationOutput
from .strategy import validate_for_backtest


class BacktestResult(BaseModel):
    id: str = Field(default_factory=lambda: f"backtest_{uuid4().hex}")
    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    bar_count: int
    initial_capital: float
    fees_bps: float
    slippage_bps: float
    data_provider: str
    data_freshness: str
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[float] = Field(default_factory=list)
    metrics: BacktestMetrics
    integrity_notes: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestEngine:
    """Deterministic historical simulation: validate -> data -> simulate ->
    metrics -> integrity checks -> result (rule 25). Every run documents
    its own timing/data assumptions rather than presenting results as
    guaranteed future performance (rule 26/64)."""

    def __init__(self, candle_service: CandleService, database: Database | None = None, evaluator: StrategyEvaluator | None = None):
        self.candle_service = candle_service
        self.database = database
        self.simulator = BarSimulator(evaluator or StrategyEvaluator())

    async def run(
        self,
        spec: StrategySpec,
        symbol: str,
        *,
        initial_capital: float = 100_000.0,
        fees_bps: float = 2.0,
        slippage_bps: float = 5.0,
        timeframe: str | None = None,
        lookback: int = 500,
        max_bars: int = 5000,
    ) -> BacktestResult:
        timeframe = timeframe or spec.timeframe
        series = await self.candle_service.get_candles(symbol, timeframe, lookback)
        result = self.run_on_candles(
            spec, symbol, series.candles, provider=series.provider, freshness=series.freshness.value,
            initial_capital=initial_capital, fees_bps=fees_bps, slippage_bps=slippage_bps, timeframe=timeframe, max_bars=max_bars,
        )
        if self.database is not None:
            await self._save(result)
        return result

    def run_on_candles(
        self,
        spec: StrategySpec,
        symbol: str,
        candles: list,
        *,
        provider: str,
        freshness: str,
        initial_capital: float = 100_000.0,
        fees_bps: float = 2.0,
        slippage_bps: float = 5.0,
        timeframe: str | None = None,
        max_bars: int = 5000,
    ) -> BacktestResult:
        """Runs a simulation against an already-resolved candle slice —
        used directly by walk-forward so each split never re-fetches or
        leaks data across dev/validation/out-of-sample boundaries."""
        timeframe = timeframe or spec.timeframe
        validate_for_backtest(spec, candles, max_bars=max_bars)

        output: SimulationOutput = self.simulator.run(
            spec, candles, initial_capital=initial_capital, fees_bps=fees_bps, slippage_bps=slippage_bps,
        )
        metrics = compute_metrics(output, initial_capital, len(candles))

        integrity_notes = [
            "Indicator timing: fields at bar i are computed only from candles[0:i+1] (no future bar is visible).",
            "Execution timing: a signal generated at bar i fills at bar i+1's open price, never at bar i's own close.",
            f"Data assumptions: {provider} candles ({freshness}); fees={fees_bps}bps, slippage={slippage_bps}bps applied per fill.",
            "Survivorship limitation: the underlying market-data provider does not model delisted/renamed symbols; "
            "a backtest over a fixed symbol list can overstate returns versus the true historical universe.",
        ]

        return BacktestResult(
            strategy_name=spec.name, strategy_version=spec.version, symbol=symbol.upper(), timeframe=timeframe,
            bar_count=len(candles), initial_capital=initial_capital, fees_bps=fees_bps, slippage_bps=slippage_bps,
            data_provider=provider, data_freshness=freshness,
            trades=output.trades, equity_curve=output.equity_curve, metrics=metrics, integrity_notes=integrity_notes,
        )

    async def _save(self, result: BacktestResult) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            "INSERT INTO backtest_results(id, strategy_id, strategy_name, result_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (result.id, None, result.strategy_name, result.model_dump_json(), result.generated_at.isoformat()),
        )
        await connection.commit()

    async def list_results(self, strategy_name: str | None = None) -> list[BacktestResult]:
        if self.database is None:
            return []
        connection = self.database.require_connection()
        if strategy_name:
            rows = await (await connection.execute(
                "SELECT result_json FROM backtest_results WHERE strategy_name = ? ORDER BY created_at DESC", (strategy_name,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT result_json FROM backtest_results ORDER BY created_at DESC")).fetchall()
        return [BacktestResult.model_validate_json(row["result_json"]) for row in rows]
