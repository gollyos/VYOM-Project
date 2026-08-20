from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.alerts.conditions import AlertContext
from app.alerts.schemas import Alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.post("", response_model=Alert)
async def create_alert(alert: Alert, request: Request) -> Alert:
    return await request.app.state.alert_engine.create(alert)


@router.get("", response_model=list[Alert])
async def list_alerts(request: Request, enabled_only: bool = False) -> list[Alert]:
    return await request.app.state.alert_engine.store.list(enabled_only=enabled_only)


@router.post("/{alert_id}/disable", response_model=Alert)
async def disable_alert(alert_id: str, request: Request) -> Alert:
    try:
        return await request.app.state.alert_engine.disable(alert_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/check")
async def check_alerts(request: Request) -> dict:
    """Manual/scheduled trigger for deterministic condition checking
    (rule 40) — used by market-monitor automation rather than a per-tick
    model call."""

    async def context_provider(alert: Alert) -> AlertContext:
        quote = None
        if alert.condition.symbol:
            try:
                quote = await request.app.state.quote_service.get_quote(alert.condition.symbol)
            except RuntimeError:
                quote = None
        return AlertContext(quote=quote)

    triggered = await request.app.state.alert_engine.check_all(context_provider)
    return {"triggered": [alert.id for alert in triggered]}
