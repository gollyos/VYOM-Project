from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.finance.schemas import Instrument, Portfolio
from app.risk.engine import RiskDecisionType
from app.trading.schemas import JournalEntry, OrderSide, OrderType, PaperOrder, TradeSetup
from app.trading.trade_manager import TradeProposal

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


@router.get("/portfolio", response_model=Portfolio)
async def get_paper_portfolio(request: Request) -> Portfolio:
    return await request.app.state.paper_broker.get_or_create_portfolio(
        starting_cash=request.app.state.risk_rules.starting_cash,
        base_currency=request.app.state.risk_rules.base_currency,
    )


@router.post("/setup/propose", response_model=TradeProposal)
async def propose_setup(setup: TradeSetup, account_size: float, risk_percentage: float, request: Request, approved: bool = False) -> TradeProposal:
    """Risk-checks `setup` and only places a PAPER order when `approved`
    is explicitly true (rule 18: manual approval is the default)."""
    portfolio = await request.app.state.paper_broker.get_or_create_portfolio(
        starting_cash=request.app.state.risk_rules.starting_cash, base_currency=request.app.state.risk_rules.base_currency,
    )
    return await request.app.state.trade_manager.propose(setup, portfolio, account_size=account_size, risk_percentage=risk_percentage, approved=approved)


@router.post("/orders", response_model=PaperOrder)
async def place_paper_order(symbol: str, side: OrderSide, quantity: float, order_type: OrderType, request: Request, requested_price: float | None = None) -> PaperOrder:
    """Places a PAPER order directly (bypassing the setup/risk convenience
    flow) — still fully simulated; no real broker exists in this codebase."""
    portfolio = await request.app.state.paper_broker.get_or_create_portfolio(
        starting_cash=request.app.state.risk_rules.starting_cash, base_currency=request.app.state.risk_rules.base_currency,
    )
    return await request.app.state.paper_broker.place_order(
        portfolio, Instrument(symbol=symbol), side, quantity, order_type, requested_price=requested_price,
    )


@router.post("/orders/{order_id}/cancel", response_model=PaperOrder)
async def cancel_paper_order(order_id: str, request: Request) -> PaperOrder:
    try:
        return await request.app.state.paper_broker.cancel_order(order_id)
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/journal", response_model=list[JournalEntry])
async def list_journal(request: Request, portfolio_id: str | None = None) -> list[JournalEntry]:
    return await request.app.state.journal_store.list(portfolio_id)


@router.post("/kill-switch/pause")
async def pause_paper_trading(request: Request) -> dict:
    """`VYOM stop paper trading` must execute immediately (rule 52) — this
    bypasses the normal task/approval flow entirely, mirroring
    `/api/desktop/emergency-pause`. It affects only PAPER records."""
    request.app.state.paper_kill_switch.pause_all()
    portfolio = await request.app.state.paper_broker.get_or_create_portfolio(
        starting_cash=request.app.state.risk_rules.starting_cash, base_currency=request.app.state.risk_rules.base_currency,
    )
    cancelled = await request.app.state.paper_kill_switch.cancel_pending(
        request.app.state.paper_broker, request.app.state.paper_order_store, portfolio.id,
    )
    return {"paused": True, "cancelled_orders": cancelled}


@router.post("/kill-switch/close-positions")
async def close_paper_positions(request: Request) -> dict:
    portfolio = await request.app.state.paper_broker.get_or_create_portfolio(
        starting_cash=request.app.state.risk_rules.starting_cash, base_currency=request.app.state.risk_rules.base_currency,
    )
    closed = await request.app.state.paper_kill_switch.close_simulated_positions(request.app.state.paper_broker, portfolio)
    return {"closed_symbols": closed}


@router.post("/kill-switch/resume")
async def resume_paper_trading(request: Request) -> dict:
    request.app.state.paper_kill_switch.resume()
    return {"paused": False}


@router.get("/risk-status")
async def risk_status(request: Request) -> dict:
    kill_switch = request.app.state.risk_kill_switch
    return {"active": kill_switch.is_active(), "reason": kill_switch.reason()}
