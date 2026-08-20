from __future__ import annotations

from pydantic import BaseModel

from .schemas import Portfolio


class PnLSummary(BaseModel):
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    cash: float
    total_market_value: float
    total_value: float
    priced_positions: int
    unpriced_positions: int


def compute_pnl(portfolio: Portfolio) -> PnLSummary:
    """Computes P&L only from positions that actually carry a current
    price; unpriced positions are counted but never assumed at cost as if
    that were a real gain/loss (rule 6)."""
    priced = [p for p in portfolio.positions if p.current_price is not None]
    unpriced = [p for p in portfolio.positions if p.current_price is None]
    unrealized = sum(p.unrealized_pnl or 0.0 for p in priced)
    market_value = sum((p.market_value or 0.0) for p in priced) + sum(p.cost_basis for p in unpriced)
    return PnLSummary(
        realized_pnl=portfolio.realized_pnl,
        unrealized_pnl=unrealized,
        total_pnl=portfolio.realized_pnl + unrealized,
        cash=portfolio.cash,
        total_market_value=market_value,
        total_value=portfolio.cash + market_value,
        priced_positions=len(priced),
        unpriced_positions=len(unpriced),
    )
