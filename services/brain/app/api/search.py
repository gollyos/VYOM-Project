from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/search", tags=["search"])


class SerpApiConnectRequest(BaseModel):
    api_key: str


@router.post("/serpapi/connect")
async def connect_serpapi(payload: SerpApiConnectRequest, request: Request) -> dict:
    """Verifies the key against a real SerpAPI search call before storing
    it — connect never reports success on an unverified key. Restart
    the Brain to activate it in DeepResearchTask.from_config() (read
    once at startup, matching how GOOGLE_OAUTH_CLIENT_ID/_SECRET work)."""
    from app.research.source_discovery import SerpApiSearchProvider

    provider = SerpApiSearchProvider(payload.api_key)
    healthy, error = await provider.health()
    if not healthy:
        raise HTTPException(status_code=401, detail=error or "SerpAPI key rejected")
    request.app.state.secret_vault.set("token:serpapi", payload.api_key.encode("utf-8"))
    return {"status": "connected", "note": "Restart the Brain to activate SerpAPI for research tasks."}


@router.post("/serpapi/disconnect")
async def disconnect_serpapi(request: Request) -> dict:
    request.app.state.secret_vault.delete("token:serpapi")
    return {"status": "disconnected", "note": "Restart the Brain to deactivate SerpAPI."}


@router.get("/serpapi/status")
async def serpapi_status(request: Request) -> dict:
    from app.research.source_discovery import SerpApiSearchProvider

    raw = request.app.state.secret_vault.get("token:serpapi")
    if raw is None:
        return {"connected": False, "detail": "SerpAPI is not connected"}
    provider = SerpApiSearchProvider(raw.decode("utf-8"))
    healthy, error = await provider.health()
    return {"connected": healthy, "detail": error}
