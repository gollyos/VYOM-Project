from __future__ import annotations

import math

from pydantic import BaseModel

from app.finance.metrics import compute_drawdown

from .simulator import BacktestTrade, SimulationOutput


class BacktestMetrics(BaseModel):
    trade_count: int
    win_rate_pct: float | None = None
    profit_factor: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    expectancy: float | None = None
    total_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    exposure_pct: float | None = None
    sharpe_like: float | None = None
    sortino_like: float | None = None


def compute_metrics(output: SimulationOutput, initial_capital: float, total_bars: int) -> BacktestMetrics:
    """All ratios are computed only when the underlying sample supports
    them; an unsupported metric is left `None`, never fabricated
    (rule 6/31)."""
    trades: list[BacktestTrade] = output.trades
    metrics = BacktestMetrics(trade_count=len(trades))
    if not trades:
        return metrics

    wins = [t for t in trades if (t.pnl or 0) > 0]
    losses = [t for t in trades if (t.pnl or 0) < 0]
    metrics.win_rate_pct = round(len(wins) / len(trades) * 100, 2)

    gross_profit = sum(t.pnl for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0
    metrics.average_win = round(gross_profit / len(wins), 4) if wins else None
    metrics.average_loss = round(-gross_loss / len(losses), 4) if losses else None
    if gross_loss > 0:
        metrics.profit_factor = round(gross_profit / gross_loss, 4)

    win_rate = len(wins) / len(trades)
    avg_win = metrics.average_win or 0.0
    avg_loss = metrics.average_loss or 0.0
    metrics.expectancy = round(win_rate * avg_win + (1 - win_rate) * avg_loss, 4)

    if initial_capital > 0 and output.final_capital:
        metrics.total_return_pct = round(((output.final_capital / initial_capital) - 1) * 100, 4)

    drawdown = compute_drawdown(output.equity_curve) if len(output.equity_curve) >= 2 else None
    metrics.max_drawdown_pct = drawdown.max_drawdown_pct if drawdown else None

    bars_in_position = sum(1 for t in trades if t.exit_time)
    metrics.exposure_pct = round(min(100.0, (bars_in_position / total_bars) * 100), 2) if total_bars else None

    returns = [t.return_pct / 100 for t in trades if t.return_pct is not None]
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        stdev = math.sqrt(variance)
        if stdev > 0:
            metrics.sharpe_like = round(mean / stdev, 4)
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            downside_variance = sum(r ** 2 for r in downside) / len(downside)
            downside_stdev = math.sqrt(downside_variance)
            if downside_stdev > 0:
                metrics.sortino_like = round(mean / downside_stdev, 4)

    return metrics
