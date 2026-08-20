from __future__ import annotations

from app.market_data.schemas import Quote

from .schemas import OrderSide, OrderType, PaperOrder


class OrderSimulator:
    """Deterministic simulated fill logic. Slippage/fees are configurable
    assumptions (rule 17), never hidden inside a fixed constant."""

    def try_fill(self, order: PaperOrder, quote: Quote) -> bool:
        """Attempts to fill `order` against `quote` in place. Returns True
        if the order filled. Market orders always fill; limit/stop orders
        fill only when the current price satisfies the trigger."""
        if order.order_type == OrderType.MARKET:
            fill_price = self._apply_slippage(quote.price, order)
            self._fill(order, fill_price)
            return True

        if order.requested_price is None:
            return False

        if order.order_type == OrderType.LIMIT:
            triggered = (
                (order.side == OrderSide.BUY and quote.price <= order.requested_price)
                or (order.side == OrderSide.SELL and quote.price >= order.requested_price)
            )
            if triggered:
                fill_price = self._apply_slippage(min(quote.price, order.requested_price) if order.side == OrderSide.BUY else max(quote.price, order.requested_price), order)
                self._fill(order, fill_price)
                return True
            return False

        if order.order_type == OrderType.STOP:
            triggered = (
                (order.side == OrderSide.BUY and quote.price >= order.requested_price)
                or (order.side == OrderSide.SELL and quote.price <= order.requested_price)
            )
            if triggered:
                fill_price = self._apply_slippage(quote.price, order)
                self._fill(order, fill_price)
                return True
            return False

        return False

    def _apply_slippage(self, price: float, order: PaperOrder) -> float:
        bps = order.slippage_assumption_bps / 10_000
        direction = 1 if order.side == OrderSide.BUY else -1
        return round(price * (1 + direction * bps), 6)

    def _fill(self, order: PaperOrder, fill_price: float) -> None:
        from datetime import datetime, timezone

        from .schemas import OrderStatus

        order.fill_price = fill_price
        order.status = OrderStatus.FILLED
        order.filled_at = datetime.now(timezone.utc)
        notional = fill_price * order.quantity
        order.fees_paid = round(notional * (order.fee_assumption_bps / 10_000), 6)
