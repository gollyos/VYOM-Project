from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.finance.schemas import Instrument, Portfolio
from app.risk.engine import RiskDecision, RiskDecisionType, RiskEngine
from app.trading.paper_broker import PaperBroker
from app.trading.position_sizing import PositionSizingInput, PositionSizingResult, calculate_position_size
from app.trading.schemas import OrderSide, OrderType, PaperOrder, SetupStatus, TradeSetup


class TradeProposalOutcome(str, Enum):
    PLACED = "placed"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"


class TradeProposal(BaseModel):
    outcome: TradeProposalOutcome
    setup: TradeSetup
    sizing: PositionSizingResult
    risk_decision: RiskDecision
    order: PaperOrder | None = None


class TradeManager:
    """Orchestrates idea -> setup -> risk validation -> paper approval ->
    paper order -> fill (rule 20). Approval mode defaults to `manual`
    (rule 18/51): a setup that passes risk still stops at
    `PENDING_APPROVAL` unless the caller has already obtained explicit
    approval for this specific trade."""

    def __init__(self, risk_engine: RiskEngine, paper_broker: PaperBroker):
        self.risk_engine = risk_engine
        self.paper_broker = paper_broker

    def size_and_check(
        self, setup: TradeSetup, portfolio: Portfolio, *, account_size: float, risk_percentage: float
    ) -> tuple[PositionSizingResult, RiskDecision]:
        entry = sum(setup.entry_zone) / len(setup.entry_zone)
        sizing = calculate_position_size(PositionSizingInput(
            account_size=account_size, risk_percentage=risk_percentage, entry=entry, stop=setup.stop,
            max_position_value=portfolio.cash,
        ))
        setup.max_risk = sizing.risk_amount
        decision = self.risk_engine.evaluate(setup, sizing, portfolio)
        return sizing, decision

    async def propose(
        self,
        setup: TradeSetup,
        portfolio: Portfolio,
        *,
        account_size: float,
        risk_percentage: float,
        approved: bool = False,
    ) -> TradeProposal:
        sizing, decision = self.size_and_check(setup, portfolio, account_size=account_size, risk_percentage=risk_percentage)

        if decision.decision == RiskDecisionType.REJECT:
            setup.status = SetupStatus.INVALIDATED
            return TradeProposal(outcome=TradeProposalOutcome.REJECTED, setup=setup, sizing=sizing, risk_decision=decision)

        position_size = decision.adjusted_position_size if decision.decision == RiskDecisionType.REDUCE else sizing.position_size
        setup.status = SetupStatus.READY_FOR_PAPER

        if not approved:
            return TradeProposal(outcome=TradeProposalOutcome.PENDING_APPROVAL, setup=setup, sizing=sizing, risk_decision=decision)

        side = OrderSide.BUY if setup.direction.value == "long" else OrderSide.SELL
        order = await self.paper_broker.place_order(
            portfolio, Instrument(symbol=setup.instrument), side, position_size or 0.0, OrderType.MARKET, setup_id=setup.id,
        )
        setup.status = SetupStatus.PAPER_OPEN if order.status.value == "filled" else SetupStatus.READY_FOR_PAPER
        return TradeProposal(outcome=TradeProposalOutcome.PLACED, setup=setup, sizing=sizing, risk_decision=decision, order=order)
