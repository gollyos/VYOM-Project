from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from .conditions import AlertContext, ConditionEvaluator
from .schemas import Alert, AlertStatus
from .store import AlertStore

EmitFn = Callable[[str, str, dict], Awaitable[None]]
ContextProviderFn = Callable[[Alert], Awaitable[AlertContext]]


class AlertEngine:
    """Deterministic condition checking (rule 40) — no model call per
    price tick. Cooldown prevents repeated notification spam for the same
    condition (rule 39)."""

    def __init__(self, store: AlertStore, evaluator: ConditionEvaluator | None = None):
        self.store = store
        self.evaluator = evaluator or ConditionEvaluator()

    async def check_all(self, context_provider: ContextProviderFn, *, emit: EmitFn | None = None) -> list[Alert]:
        triggered: list[Alert] = []
        alerts = await self.store.list(enabled_only=True)
        for alert in alerts:
            now = datetime.now(timezone.utc)
            if alert.last_triggered is not None:
                elapsed = (now - alert.last_triggered).total_seconds()
                if elapsed < alert.cooldown_seconds:
                    continue
            try:
                context = await context_provider(alert)
            except Exception:
                continue
            alert.last_checked = now
            if self.evaluator.evaluate(alert.condition, context):
                alert.last_triggered = now
                alert.trigger_count += 1
                triggered.append(alert)
                if emit is not None:
                    await emit("market_alert_triggered", f"Alert triggered: {alert.name}", {"alert_id": alert.id, "condition": alert.condition.model_dump(mode="json")})
            await self.store.save(alert)
        return triggered

    async def create(self, alert: Alert) -> Alert:
        return await self.store.save(alert)

    async def disable(self, alert_id: str) -> Alert:
        alert = await self.store.get(alert_id)
        if alert is None:
            raise KeyError(alert_id)
        alert.status = AlertStatus.DISABLED
        return await self.store.save(alert)
