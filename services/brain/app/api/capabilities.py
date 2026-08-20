from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("")
async def list_capabilities(request: Request, q: str = "") -> list[dict]:
    values = request.app.state.capability_registry.search(q, limit=100) if q else request.app.state.capability_registry.list()
    return [item.model_dump(mode="json") for item in values]
