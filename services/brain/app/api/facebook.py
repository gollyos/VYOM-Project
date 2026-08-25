from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.facebook.schemas import FacebookConnectRequest, FacebookPostReceipt, FacebookPostRequest

router = APIRouter(prefix="/api/facebook", tags=["facebook"])


@router.post("/connect")
async def connect(payload: FacebookConnectRequest, request: Request) -> dict:
    """Connects via a long-lived Page access token + Page ID (Graph API
    Explorer, or a Meta app in Development Mode with yourself as Page
    admin — no App Review needed for posting to your own Page).
    Verifies by actually querying the Page before reporting success."""
    provider = request.app.state.facebook_provider
    provider.store_credentials(payload.page_id, payload.access_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Facebook connect failed")
    return {"status": "connected", "page_id": payload.page_id}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.facebook_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.facebook_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/post", response_model=FacebookPostReceipt)
async def post_update(payload: FacebookPostRequest, request: Request) -> FacebookPostReceipt:
    try:
        return await request.app.state.facebook_service.post(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
