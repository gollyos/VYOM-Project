from __future__ import annotations

from fastapi import APIRouter, Request

from app.desktop.schemas import DisplayInfo

router = APIRouter(prefix="/api/screen", tags=["screen"])


@router.get("/displays", response_model=list[DisplayInfo])
async def displays(request: Request) -> list[DisplayInfo]:
    return request.app.state.window_manager.displays()
