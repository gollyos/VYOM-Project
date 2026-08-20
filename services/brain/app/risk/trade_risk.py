from __future__ import annotations

from pydantic import BaseModel, Field

from app.finance.schemas import Portfolio
from app.trading.position_sizing import PositionSizingResult
from app.trading.schemas import TradeSetup

from .rules import RiskRules


class TradeRiskCheck(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    risk_pct_of_equity: float
    projected_symbol_exposure_pct: float
    projected_open_positions: int


def evaluate_trade_risk(setup: TradeSetup, sizing: PositionSizingResult, portfolio: Portfolio, rules: RiskRules) -> TradeRiskCheck:
    """Checks one proposed trade against per-trade risk limits. Pure
    function over inputs — no hidden state, so results are reproducible
    and testable (rule 15)."""
    reasons: list[str] = []
    total_value = portfolio.total_value() or rules.starting_cash

    risk_pct = (sizing.risk_amount / total_value) * 100 if total_value > 0 else 100.0
    if risk_pct > rules.max_risk_per_trade_pct:
        reasons.append(
            f"Risk per trade {risk_pct:.2f}% exceeds max_risk_per_trade_pct ({rules.max_risk_per_trade_pct}%)"
        )

    existing_position = portfolio.find_position(setup.instrument)
    existing_value = existing_position.market_value or existing_position.cost_basis if existing_position else 0.0
    projected_symbol_value = existing_value + sizing.position_value
    projected_symbol_pct = (projected_symbol_value / total_value) * 100 if total_value > 0 else 100.0
    if projected_symbol_pct > rules.max_single_symbol_exposure_pct:
        reasons.append(
            f"Projected {setup.instrument} exposure {projected_symbol_pct:.2f}% would exceed "
            f"max_single_symbol_exposure_pct ({rules.max_single_symbol_exposure_pct}%)"
        )

    projected_positions = len(portfolio.positions) + (0 if existing_position else 1)
    if projected_positions > rules.max_open_positions:
        reasons.append(f"Opening this position would exceed max_open_positions ({rules.max_open_positions})")

    return TradeRiskCheck(
        passed=not reasons, reasons=reasons, risk_pct_of_equity=round(risk_pct, 4),
        projected_symbol_exposure_pct=round(projected_symbol_pct, 4), projected_open_positions=projected_positions,
    )
