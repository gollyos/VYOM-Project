from __future__ import annotations

from .engine import BacktestResult


class BacktestReport:
    """Builds a human-readable summary and Composer-ready rows from a
    `BacktestResult`. Never claims guaranteed future performance
    (rule 26/64)."""

    def summarize(self, result: BacktestResult) -> str:
        metrics = result.metrics
        if metrics.trade_count == 0:
            return (
                f"{result.strategy_name} v{result.strategy_version} on {result.symbol}: no trades were "
                f"generated over {result.bar_count} bars. Past simulated results never guarantee future performance."
            )
        parts = [
            f"{result.strategy_name} v{result.strategy_version} on {result.symbol} ({result.bar_count} bars): "
            f"{metrics.trade_count} trade(s), win rate {metrics.win_rate_pct}%, "
        ]
        if metrics.profit_factor is not None:
            parts.append(f"profit factor {metrics.profit_factor}, ")
        if metrics.total_return_pct is not None:
            parts.append(f"total return {metrics.total_return_pct}%, ")
        if metrics.max_drawdown_pct is not None:
            parts.append(f"max drawdown {metrics.max_drawdown_pct}%. ")
        parts.append("This is a simulated historical result, not a guarantee of future performance.")
        return "".join(parts)

    def equity_curve_rows(self, result: BacktestResult) -> list[list[float]]:
        return [[index, value] for index, value in enumerate(result.equity_curve)]

    def trade_rows(self, result: BacktestResult) -> list[list]:
        return [
            [trade.entry_time.isoformat(), trade.exit_time.isoformat() if trade.exit_time else "open", trade.entry_price, trade.exit_price, trade.pnl]
            for trade in result.trades
        ]
