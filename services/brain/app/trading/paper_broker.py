from __future__ import annotations

from app.finance.schemas import Instrument, Portfolio, PortfolioKind, Position
from app.finance.store import PortfolioStore
from app.market_data.quotes import QuoteService

from .order_simulator import OrderSimulator
from .schemas import OrderSide, OrderStatus, OrderType, PaperOrder
from .store import PaperOrderStore


class InsufficientCashError(Exception):
    pass


class PaperBroker:
    """Local paper-trading broker (rule 16). Every order/position it
    produces is labeled PAPER and persisted separately from any future real
    broker integration — see docs/PAPER_TRADING.md. No live order
    execution path exists anywhere in this class."""

    def __init__(
        self,
        portfolio_store: PortfolioStore,
        order_store: PaperOrderStore,
        quote_service: QuoteService,
        simulator: OrderSimulator | None = None,
    ):
        self.portfolio_store = portfolio_store
        self.order_store = order_store
        self.quote_service = quote_service
        self.simulator = simulator or OrderSimulator()

    async def get_or_create_portfolio(self, name: str = "Paper Portfolio", *, starting_cash: float = 100_000.0, base_currency: str = "USD") -> Portfolio:
        existing = [p for p in await self.portfolio_store.list(kind=PortfolioKind.PAPER.value) if p.name == name]
        if existing:
            return existing[0]
        portfolio = Portfolio(name=name, kind=PortfolioKind.PAPER, base_currency=base_currency, cash=starting_cash)
        return await self.portfolio_store.save(portfolio)

    async def place_order(
        self,
        portfolio: Portfolio,
        instrument: Instrument,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        *,
        requested_price: float | None = None,
        setup_id: str | None = None,
        slippage_bps: float = 5.0,
        fee_bps: float = 2.0,
    ) -> PaperOrder:
        if portfolio.kind != PortfolioKind.PAPER:
            raise ValueError("Orders may only be placed against a PAPER portfolio")
        if quantity <= 0:
            raise ValueError("Order quantity must be positive")

        order = PaperOrder(
            portfolio_id=portfolio.id, setup_id=setup_id, symbol=instrument.normalized_symbol(),
            side=side, quantity=quantity, order_type=order_type, requested_price=requested_price,
            slippage_assumption_bps=slippage_bps, fee_assumption_bps=fee_bps,
        )

        quote = await self.quote_service.get_quote(instrument.normalized_symbol())
        filled = self.simulator.try_fill(order, quote)
        if filled:
            self._apply_fill(portfolio, instrument, order)
            await self.portfolio_store.save(portfolio)
        else:
            order.status = OrderStatus.PENDING

        await self.order_store.save(order)
        return order

    def _apply_fill(self, portfolio: Portfolio, instrument: Instrument, order: PaperOrder) -> None:
        assert order.fill_price is not None
        notional = order.fill_price * order.quantity
        total_cost = notional + (order.fees_paid or 0.0)

        if order.side == OrderSide.BUY:
            if portfolio.cash < total_cost:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = f"Insufficient paper cash: needs {total_cost:.2f}, has {portfolio.cash:.2f}"
                return
            portfolio.cash -= total_cost
            existing = portfolio.find_position(instrument.normalized_symbol())
            if existing is None:
                portfolio.positions.append(Position(instrument=instrument, quantity=order.quantity, average_price=order.fill_price, current_price=order.fill_price))
            else:
                total_qty = existing.quantity + order.quantity
                existing.average_price = ((existing.quantity * existing.average_price) + notional) / total_qty
                existing.quantity = total_qty
                existing.current_price = order.fill_price
        else:  # SELL
            existing = portfolio.find_position(instrument.normalized_symbol())
            if existing is None or existing.quantity < order.quantity:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "Insufficient paper position quantity to sell"
                return
            realized = (order.fill_price - existing.average_price) * order.quantity - (order.fees_paid or 0.0)
            portfolio.realized_pnl += realized
            portfolio.cash += notional - (order.fees_paid or 0.0)
            existing.quantity -= order.quantity
            existing.current_price = order.fill_price
            if existing.quantity <= 0:
                portfolio.positions.remove(existing)

    async def cancel_order(self, order_id: str) -> PaperOrder:
        order = await self.order_store.get(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot cancel an order in status {order.status.value}")
        order.status = OrderStatus.CANCELLED
        await self.order_store.save(order)
        return order

    async def recheck_pending(self, portfolio: Portfolio) -> list[PaperOrder]:
        """Re-evaluates every pending order for `portfolio` against a fresh
        quote (rule 16). Used by scheduled market monitoring rather than
        continuous polling of every price tick (rule 40)."""
        pending = await self.order_store.list(portfolio.id, status=OrderStatus.PENDING.value)
        filled: list[PaperOrder] = []
        for order in pending:
            quote = await self.quote_service.get_quote(order.symbol)
            instrument = Instrument(symbol=order.symbol)
            if self.simulator.try_fill(order, quote):
                self._apply_fill(portfolio, instrument, order)
                await self.order_store.save(order)
                filled.append(order)
        if filled:
            await self.portfolio_store.save(portfolio)
        return filled
