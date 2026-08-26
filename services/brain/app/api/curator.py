from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/curator", tags=["curator"])


@router.get("/runs")
async def recent_runs(request: Request, limit: int = 10) -> dict:
    """Recent curator pass history (see app/adaptive/curator.py) - each
    run's knowledge-lint findings and paused-automation check, so the
    user can see what VYOM's own background self-review has been doing
    without digging through logs."""
    store = request.app.state.curator_run_store
    runs = await store.recent(min(max(limit, 1), 50))
    return {"count": len(runs), "runs": runs}


@router.post("/run-now")
async def run_now(request: Request) -> dict:
    """Manually trigger a curator pass immediately, bypassing the idle
    gate - for testing or an impatient user who doesn't want to wait for
    natural idle time."""
    curator = request.app.state.curator
    summary = await curator.run_once()
    return {"status": "completed", "summary": summary}
