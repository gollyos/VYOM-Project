from __future__ import annotations

from .schemas import JournalEntry, PaperOrder, TradeDirection, TradeResult
from .store import JournalStore


class JournalService:
    """Every simulated trade produces a journal entry (rule 21). Learning
    from journal outcomes must go through the Phase 6 learning system's
    evidence rules (rule 22) — this service only records facts; it does not
    itself draw generalized conclusions from a single trade."""

    def __init__(self, store: JournalStore):
        self.store = store

    async def open_entry(
        self,
        *,
        portfolio_id: str,
        symbol: str,
        direction: TradeDirection,
        entry_order: PaperOrder,
        setup_id: str | None = None,
        thesis_id: str | None = None,
        risk_amount: float | None = None,
        sources: list[str] | None = None,
        models_involved: list[str] | None = None,
    ) -> JournalEntry:
        entry = JournalEntry(
            setup_id=setup_id, thesis_id=thesis_id, portfolio_id=portfolio_id, symbol=symbol, direction=direction,
            entry_price=entry_order.fill_price, entry_time=entry_order.filled_at,
            risk_amount=risk_amount, result=TradeResult.OPEN,
            sources=sources or [], models_involved=models_involved or [],
        )
        return await self.store.save(entry)

    async def close_entry(self, entry_id: str, exit_order: PaperOrder, *, mistakes: list[str] | None = None, what_worked: list[str] | None = None) -> JournalEntry:
        entry = await self.store.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.exit_price = exit_order.fill_price
        entry.exit_time = exit_order.filled_at
        if entry.entry_price is not None and exit_order.fill_price is not None:
            sign = 1 if entry.direction == TradeDirection.LONG else -1
            quantity = exit_order.quantity
            entry.pnl = round(sign * (exit_order.fill_price - entry.entry_price) * quantity - (exit_order.fees_paid or 0.0), 4)
            if entry.pnl > 0:
                entry.result = TradeResult.WIN
            elif entry.pnl < 0:
                entry.result = TradeResult.LOSS
            else:
                entry.result = TradeResult.BREAKEVEN
        if entry.entry_time and entry.exit_time:
            entry.duration_seconds = (entry.exit_time - entry.entry_time).total_seconds()
        entry.mistakes = mistakes or entry.mistakes
        entry.what_worked = what_worked or entry.what_worked
        return await self.store.save(entry)
