from __future__ import annotations

from datetime import datetime, timezone

from .rules import RiskRules


class RiskKillSwitch:
    """Automatic pause of new paper entries when a hard rule is breached
    (rule 53). This never relaxes/raises a limit — it only ever *adds* a
    block on top of the normal Risk Engine checks. Resuming requires an
    explicit separate action (rule 62), never an automatic clear."""

    def __init__(self, rules: RiskRules):
        self.rules = rules
        self._active = False
        self._reason: str | None = None
        self._triggered_at: datetime | None = None

    def is_active(self) -> bool:
        return self._active

    def reason(self) -> str | None:
        return self._reason

    def trigger(self, reason: str) -> None:
        self._active = True
        self._reason = reason
        self._triggered_at = datetime.now(timezone.utc)

    def resume(self) -> None:
        """Explicit user-only action; nothing in this module calls this
        automatically."""
        self._active = False
        self._reason = None

    def check_daily_loss(self, day_start_equity: float, current_equity: float) -> bool:
        if not self.rules.pause_on_daily_loss_breach or day_start_equity <= 0:
            return False
        loss_pct = ((day_start_equity - current_equity) / day_start_equity) * 100
        if loss_pct >= self.rules.max_daily_loss_pct:
            self.trigger(f"Daily loss {loss_pct:.2f}% breached max_daily_loss_pct ({self.rules.max_daily_loss_pct}%)")
            return True
        return False

    def check_drawdown(self, current_drawdown_pct: float | None) -> bool:
        if not self.rules.pause_on_drawdown_breach or current_drawdown_pct is None:
            return False
        if current_drawdown_pct >= self.rules.max_drawdown_pct:
            self.trigger(f"Drawdown {current_drawdown_pct:.2f}% breached max_drawdown_pct ({self.rules.max_drawdown_pct}%)")
            return True
        return False

    def check_stale_data(self, is_stale: bool) -> bool:
        if not self.rules.pause_on_stale_data or not is_stale:
            return False
        self.trigger("Market data is stale/unreliable; new paper entries are paused")
        return True

    def check_strategy_anomaly(self, anomaly_detected: bool, description: str = "") -> bool:
        if not self.rules.pause_on_strategy_anomaly or not anomaly_detected:
            return False
        self.trigger(f"Strategy anomaly detected: {description or 'unspecified'}")
        return True


class PaperKillSwitch:
    """Emergency stop for the paper-trading subsystem only (rule 52).
    `paper.pause_all` / `paper.cancel_pending` / `paper.close_simulated_positions`
    affect exclusively PAPER records — nothing here touches a real broker,
    because no real broker integration exists in this codebase."""

    def __init__(self):
        self._paused = False

    def is_paused(self) -> bool:
        return self._paused

    def pause_all(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def cancel_pending(self, broker, order_store, portfolio_id: str) -> list[str]:
        from app.trading.schemas import OrderStatus

        pending = await order_store.list(portfolio_id, status=OrderStatus.PENDING.value)
        cancelled = []
        for order in pending:
            await broker.cancel_order(order.order_id)
            cancelled.append(order.order_id)
        return cancelled

    async def close_simulated_positions(self, broker, portfolio) -> list[str]:
        from app.finance.schemas import Instrument
        from app.trading.schemas import OrderSide, OrderType

        closed_symbols: list[str] = []
        for position in list(portfolio.positions):
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            await broker.place_order(
                portfolio, Instrument(symbol=position.instrument.normalized_symbol()), side,
                abs(position.quantity), OrderType.MARKET,
            )
            closed_symbols.append(position.instrument.normalized_symbol())
        return closed_symbols
