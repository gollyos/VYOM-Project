"""API endpoints for managing and switching VYOM personas."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.persona.manager import get_persona_manager
from app.persona.schemas import PersonaId

router = APIRouter(prefix="/api/persona", tags=["persona"])


class SwitchPersonaRequest(BaseModel):
    persona_id: str


@router.get("")
async def get_persona_status():
    """Get active persona details and list all available personas."""
    mgr = get_persona_manager()
    return {
        "active_persona": mgr.active_persona.model_dump(),
        "personas": mgr.list_personas(),
    }


@router.post("/switch")
async def switch_persona(request: SwitchPersonaRequest):
    """Switch the active persona."""
    mgr = get_persona_manager()
    try:
        new_persona = mgr.set_persona(request.persona_id)
        return {
            "success": True,
            "active_persona": new_persona.model_dump(),
            "message": f"Switched to {new_persona.name}",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
