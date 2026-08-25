from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.linkedin.schemas import LinkedInConnectRequest, LinkedInPostReceipt, LinkedInPostRequest

router = APIRouter(prefix="/api/linkedin", tags=["linkedin"])


@router.post("/connect")
async def connect(payload: LinkedInConnectRequest, request: Request) -> dict:
    """Connects via a member's OAuth 2.0 access token (obtained through
    LinkedIn's own consent screen elsewhere and pasted here). Verifies
    by actually calling LinkedIn's userinfo endpoint before reporting
    success — a stored-but-invalid token is worse than no token."""
    provider = request.app.state.linkedin_provider
    provider.store_credentials(payload.access_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "LinkedIn connect failed")
    return {"status": "connected"}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.linkedin_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.linkedin_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/post", response_model=LinkedInPostReceipt)
async def post_update(payload: LinkedInPostRequest, request: Request) -> LinkedInPostReceipt:
    try:
        return await request.app.state.linkedin_service.post(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
