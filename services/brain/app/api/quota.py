from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["quota"])


@router.get("/quota")
async def quota_state(request: Request) -> JSONResponse:
    """Today's free-tier budget per model: used, remaining, exhausted.

    "Why did VYOM go quiet at noon" is answerable from here - which model
    burned its allowance, which sibling still has room, and whether pacing
    is keeping the day alive. Also the shared reference for the voice side
    (Gemini Live draws on the same project allowance)."""
    budgeter = getattr(request.app.state, "quota_budgeter", None)
    if budgeter is None:
        return JSONResponse({"configured": False, "models": {}})
    return JSONResponse({
        "configured": True,
        "date": budgeter._date,
        "models": budgeter.snapshot(),
    })
