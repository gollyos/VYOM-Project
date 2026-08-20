from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.finance.schemas import Portfolio
from app.trading.position_sizing import PositionSizingResult
from app.trading.schemas import TradeSetup

from .kill_switch import RiskKillSwitch
from .portfolio_risk import PortfolioRiskReport, evaluate_portfolio_risk
from .rules import RiskRules
from .trade_risk import TradeRiskCheck, evaluate_trade_risk


class RiskDecisionType(str, Enum):
    PASS = "pass"
    REDUCE = "reduce"
    REJECT = "reject"


class RiskDecision(BaseModel):
    decision: RiskDecisionType
    reasons: list[str] = Field(default_factory=list)
    trade_check: TradeRiskCheck
    portfolio_check: PortfolioRiskReport
    adjusted_position_size: float | None = None


class RiskEngine:
    """Strict risk gate: TradeSetup -> Risk Engine -> PASS/REDUCE/REJECT
    (rule 15). Rules come exclusively from `config/risk.yaml`
    (`RiskRules`) — nothing here can be relaxed by an agent or model
    (rule 33/63). A hard kill-switch trip always short-circuits to REJECT
    regardless of what an individual trade's numbers look like (rule 53)."""

    def __init__(self, rules: RiskRules, kill_switch: RiskKillSwitch | None = None):
        self.rules = rules
        self.kill_switch = kill_switch

    def evaluate(
        self,
        setup: TradeSetup,
        sizing: PositionSizingResult,
        portfolio: Portfolio,
        *,
        equity_curve: list[float] | None = None,
    ) -> RiskDecision:
        if self.kill_switch is not None and self.kill_switch.is_active():
            trade_check = evaluate_trade_risk(setup, sizing, portfolio, self.rules)
            portfolio_check = evaluate_portfolio_risk(portfolio, self.rules, equity_curve)
            return RiskDecision(
                decision=RiskDecisionType.REJECT,
                reasons=[f"Risk kill switch is active: {self.kill_switch.reason()}"],
                trade_check=trade_check, portfolio_check=portfolio_check,
            )

        trade_check = evaluate_trade_risk(setup, sizing, portfolio, self.rules)
        portfolio_check = evaluate_portfolio_risk(portfolio, self.rules, equity_curve)

        hard_reasons = [r for r in trade_check.reasons if "risk per trade" not in r.lower()]
        hard_reasons += portfolio_check.reasons

        if hard_reasons:
            return RiskDecision(decision=RiskDecisionType.REJECT, reasons=hard_reasons, trade_check=trade_check, portfolio_check=portfolio_check)

        if not trade_check.passed:
            # Only the per-trade risk-percentage limit was breached; this is
            # reducible by scaling the position size down proportionally.
            scale = self.rules.max_risk_per_trade_pct / trade_check.risk_pct_of_equity if trade_check.risk_pct_of_equity > 0 else 0
            adjusted_size = round(sizing.position_size * scale, 8)
            if adjusted_size <= 0:
                return RiskDecision(decision=RiskDecisionType.REJECT, reasons=trade_check.reasons, trade_check=trade_check, portfolio_check=portfolio_check)
            return RiskDecision(
                decision=RiskDecisionType.REDUCE, reasons=trade_check.reasons,
                trade_check=trade_check, portfolio_check=portfolio_check, adjusted_position_size=adjusted_size,
            )

        return RiskDecision(decision=RiskDecisionType.PASS, reasons=[], trade_check=trade_check, portfolio_check=portfolio_check)
