from __future__ import annotations

from pydantic import BaseModel, Field

from app.finance.exposure import compute_exposure
from app.finance.metrics import compute_drawdown
from app.finance.schemas import Portfolio

from .rules import RiskRules


class PortfolioRiskReport(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    total_exposure_pct: float
    largest_sector: str | None = None
    largest_sector_pct: float = 0.0
    current_drawdown_pct: float | None = None
    max_drawdown_pct: float | None = None
    open_positions: int = 0


def evaluate_portfolio_risk(portfolio: Portfolio, rules: RiskRules, equity_curve: list[float] | None = None) -> PortfolioRiskReport:
    exposure = compute_exposure(portfolio)
    total_value = exposure.total_value or 1.0
    invested_pct = round(sum((p.market_value or p.cost_basis) for p in portfolio.positions) / total_value * 100, 4) if total_value else 0.0

    reasons: list[str] = []
    if invested_pct > rules.max_total_exposure_pct:
        reasons.append(f"Total exposure {invested_pct:.2f}% exceeds max_total_exposure_pct ({rules.max_total_exposure_pct}%)")

    largest_sector, largest_pct = None, 0.0
    for sector, pct in exposure.by_sector.items():
        if pct > largest_pct:
            largest_sector, largest_pct = sector, pct
    if largest_pct > rules.max_sector_exposure_pct:
        reasons.append(f"{largest_sector} sector exposure {largest_pct:.2f}% exceeds max_sector_exposure_pct ({rules.max_sector_exposure_pct}%)")

    drawdown = compute_drawdown(equity_curve) if equity_curve else None
    max_dd = drawdown.max_drawdown_pct if drawdown else None
    current_dd = drawdown.current_drawdown_pct if drawdown else None
    if current_dd is not None and current_dd > rules.max_drawdown_pct:
        reasons.append(f"Current drawdown {current_dd:.2f}% exceeds max_drawdown_pct ({rules.max_drawdown_pct}%)")

    if len(portfolio.positions) > rules.max_open_positions:
        reasons.append(f"{len(portfolio.positions)} open positions exceeds max_open_positions ({rules.max_open_positions})")

    return PortfolioRiskReport(
        passed=not reasons, reasons=reasons, total_exposure_pct=invested_pct,
        largest_sector=largest_sector, largest_sector_pct=round(largest_pct, 4),
        current_drawdown_pct=current_dd, max_drawdown_pct=max_dd, open_positions=len(portfolio.positions),
    )
