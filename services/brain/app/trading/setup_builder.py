from __future__ import annotations

from app.market_intelligence.schemas import TechnicalSnapshot

from .schemas import SetupStatus, TradeDirection, TradeSetup, TradeThesis


class SetupBuilder:
    """Builds a structured `TradeSetup` from a thesis and current technical
    structure. Entry/stop/targets are derived deterministically from ATR
    and recent range so a setup is never a bare guess (rule 12)."""

    def build(self, thesis: TradeThesis, snapshot: TechnicalSnapshot, *, current_price: float) -> TradeSetup:
        atr = snapshot.atr or (current_price * 0.02)
        if thesis.direction == TradeDirection.LONG:
            entry_zone = [round(current_price - atr * 0.25, 4), round(current_price + atr * 0.1, 4)]
            stop = round(current_price - atr * 1.5, 4)
            targets = [round(current_price + atr * 1.5, 4), round(current_price + atr * 3.0, 4)]
        else:
            entry_zone = [round(current_price - atr * 0.1, 4), round(current_price + atr * 0.25, 4)]
            stop = round(current_price + atr * 1.5, 4)
            targets = [round(current_price - atr * 1.5, 4), round(current_price - atr * 3.0, 4)]

        entry_mid = sum(entry_zone) / 2
        risk = abs(entry_mid - stop)
        reward = abs(targets[0] - entry_mid) if targets else 0.0
        risk_reward = round(reward / risk, 2) if risk > 0 else None

        return TradeSetup(
            instrument=thesis.instrument,
            direction=thesis.direction,
            entry_zone=entry_zone,
            stop=stop,
            targets=targets,
            risk_reward=risk_reward,
            time_horizon=thesis.time_horizon,
            thesis_id=thesis.id,
            invalidation=thesis.invalidation,
            confidence=thesis.confidence,
            status=SetupStatus.IDEA,
        )
