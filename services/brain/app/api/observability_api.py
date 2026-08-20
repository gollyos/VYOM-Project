from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/metrics")
async def metrics(request: Request) -> dict:
    return request.app.state.metrics_registry.snapshot()


@router.get("/cost")
async def cost(request: Request, days: int = 1) -> dict:
    days = max(1, min(days, 90))
    return await request.app.state.cost_tracker.summary(days=days)


@router.get("/performance")
async def performance(request: Request) -> dict:
    monitor = request.app.state.performance_monitor
    return {"budgets": monitor.budget_report()}


@router.get("/traces")
async def traces(request: Request, limit: int = 50) -> dict:
    return {"spans": request.app.state.tracer.recent(limit=min(max(limit, 1), 200))}


@router.get("/crash-reports")
async def crash_reports(request: Request) -> list[dict]:
    return request.app.state.crash_reporter.list_reports()


# -- security-session management -----------------------------------------


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = "user request"


@router.get("/sessions")
async def list_sessions(request: Request) -> list[dict]:
    return [session.model_dump(mode="json") for session in request.app.state.session_security.active_sessions()]


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(payload: RevokeRequest, request: Request) -> dict:
    count = request.app.state.session_security.revoke_all_remote(reason=payload.reason)
    await request.app.state.security_events.record("session_revoked", actor="owner", detail=f"revoked {count} session(s): {payload.reason}")
    return {"revoked": count}


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(session_id: str, payload: RevokeRequest, request: Request) -> dict:
    request.app.state.session_security.revoke_session(session_id, reason=payload.reason)
    return {"revoked": session_id}
