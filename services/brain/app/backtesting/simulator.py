from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.market_data.schemas import Candle
from app.strategies.evaluator import StrategyEvaluator, compute_fields
from app.strategies.schemas import StrategySpec


class BacktestTradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class BacktestTrade(BaseModel):
    id: str = Field(default_factory=lambda: f"bt_trade_{uuid4().hex[:10]}")
    side: BacktestTradeSide = BacktestTradeSide.LONG
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    quantity: float
    fees_paid: float = 0.0
    pnl: float | None = None
    return_pct: float | None = None


class SimulationOutput(BaseModel):
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[float] = Field(default_factory=list)
    equity_timestamps: list[datetime] = Field(default_factory=list)
    final_capital: float = 0.0


class BarSimulator:
    """Bar-by-bar deterministic simulation. At bar `i` only
    `candles[0:i+1]` is visible to the strategy (see
    `strategies.evaluator.compute_fields`); an order signaled at bar `i`
    fills at bar `i+1`'s open, never at bar `i`'s own close — this is the
    concrete lookahead-prevention mechanism (rule 26/71)."""

    def __init__(self, evaluator: StrategyEvaluator | None = None):
        self.evaluator = evaluator or StrategyEvaluator()

    def run(
        self,
        spec: StrategySpec,
        candles: list[Candle],
        *,
        initial_capital: float,
        fees_bps: float,
        slippage_bps: float,
    ) -> SimulationOutput:
        capital = initial_capital
        cash = initial_capital
        open_trade: BacktestTrade | None = None
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        equity_timestamps: list[datetime] = []
        prev_fields: dict[str, float] | None = None

        for index in range(len(candles) - 1):  # last bar has no "next open" to fill on
            fields = compute_fields(candles, index)
            next_bar = candles[index + 1]

            if open_trade is None:
                if self.evaluator.should_enter(spec, fields, prev_fields):
                    fill_price = next_bar.open * (1 + slippage_bps / 10_000)
                    quantity = cash // fill_price if fill_price > 0 else 0
                    if quantity > 0:
                        fee = fill_price * quantity * (fees_bps / 10_000)
                        cash -= (fill_price * quantity) + fee
                        open_trade = BacktestTrade(
                            entry_time=next_bar.timestamp, entry_price=round(fill_price, 6),
                            quantity=quantity, fees_paid=round(fee, 6),
                        )
            else:
                if self.evaluator.should_exit(spec, fields, prev_fields):
                    fill_price = next_bar.open * (1 - slippage_bps / 10_000)
                    fee = fill_price * open_trade.quantity * (fees_bps / 10_000)
                    proceeds = fill_price * open_trade.quantity - fee
                    cash += proceeds
                    open_trade.exit_time = next_bar.timestamp
                    open_trade.exit_price = round(fill_price, 6)
                    open_trade.fees_paid = round(open_trade.fees_paid + fee, 6)
                    open_trade.pnl = round(proceeds - (open_trade.entry_price * open_trade.quantity), 6)
                    entry_cost = open_trade.entry_price * open_trade.quantity
                    open_trade.return_pct = round((open_trade.pnl / entry_cost) * 100, 4) if entry_cost else 0.0
                    trades.append(open_trade)
                    open_trade = None

            mark_price = candles[index].close
            position_value = (open_trade.quantity * mark_price) if open_trade else 0.0
            capital = cash + position_value
            equity_curve.append(round(capital, 6))
            equity_timestamps.append(candles[index].timestamp)
            prev_fields = fields

        if open_trade is not None:
            last = candles[-1]
            open_trade.exit_time = last.timestamp
            open_trade.exit_price = last.close
            proceeds = last.close * open_trade.quantity
            cash += proceeds
            open_trade.pnl = round(proceeds - (open_trade.entry_price * open_trade.quantity), 6)
            entry_cost = open_trade.entry_price * open_trade.quantity
            open_trade.return_pct = round((open_trade.pnl / entry_cost) * 100, 4) if entry_cost else 0.0
            trades.append(open_trade)
            capital = cash
            equity_curve.append(round(capital, 6))
            equity_timestamps.append(last.timestamp)

        return SimulationOutput(trades=trades, equity_curve=equity_curve, equity_timestamps=equity_timestamps, final_capital=round(capital, 6))
