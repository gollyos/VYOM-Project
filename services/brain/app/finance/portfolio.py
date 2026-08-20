from __future__ import annotations

from app.market_data.quotes import QuoteService

from .exposure import ExposureBreakdown, compute_exposure, herfindahl_concentration
from .pnl import PnLSummary, compute_pnl
from .schemas import Portfolio, Position
from .store import PortfolioStore


class PortfolioAnalytics(PnLSummary):
    """Backwards-friendly aggregate combining P&L, exposure, and
    concentration for one Composer-ready response."""


class PortfolioService:
    def __init__(self, store: PortfolioStore, quote_service: QuoteService):
        self.store = store
        self.quote_service = quote_service

    async def get(self, portfolio_id: str) -> Portfolio:
        portfolio = await self.store.get(portfolio_id)
        if portfolio is None:
            raise KeyError(portfolio_id)
        return portfolio

    async def reprice(self, portfolio: Portfolio) -> Portfolio:
        """Refreshes `current_price` on every position from the market-data
        layer. A quote failure leaves the position unpriced rather than
        inventing a price (rule 6)."""
        for position in portfolio.positions:
            try:
                quote = await self.quote_service.get_quote(position.instrument.normalized_symbol())
                position.current_price = quote.price
            except Exception:
                continue
        return portfolio

    async def add_position(self, portfolio: Portfolio, position: Position) -> Portfolio:
        existing = portfolio.find_position(position.instrument.normalized_symbol())
        if existing is not None:
            total_quantity = existing.quantity + position.quantity
            if total_quantity != 0:
                existing.average_price = ((existing.quantity * existing.average_price) + (position.quantity * position.average_price)) / total_quantity
            existing.quantity = total_quantity
        else:
            portfolio.positions.append(position)
        await self.store.save(portfolio)
        return portfolio

    async def analytics(self, portfolio: Portfolio) -> dict:
        pnl = compute_pnl(portfolio)
        exposure = compute_exposure(portfolio)
        concentration = herfindahl_concentration(exposure)
        return {
            "pnl": pnl.model_dump(mode="json"),
            "exposure": exposure.model_dump(mode="json"),
            "concentration_hhi": concentration,
        }
