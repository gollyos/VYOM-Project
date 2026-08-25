from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.instagram.schemas import (
    InstagramConnectRequest,
    InstagramMessageReceipt,
    InstagramMessageRequest,
    InstagramPostReceipt,
    InstagramPostRequest,
)

router = APIRouter(prefix="/api/instagram", tags=["instagram"])


@router.post("/connect")
async def connect(payload: InstagramConnectRequest, request: Request) -> dict:
    """Connects via a long-lived Page access token + the account's IG
    Business Account ID (Meta Graph API Explorer, or a Meta app in
    Development Mode with yourself as tester — no App Review needed for
    posting to your own account). Verifies by actually querying the
    account before reporting success."""
    provider = request.app.state.instagram_provider
    provider.store_credentials(payload.instagram_business_account_id, payload.access_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Instagram connect failed")
    return {"status": "connected", "instagram_business_account_id": payload.instagram_business_account_id}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.instagram_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.instagram_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/post", response_model=InstagramPostReceipt)
async def post_media(payload: InstagramPostRequest, request: Request) -> InstagramPostReceipt:
    try:
        return await request.app.state.instagram_service.post(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/message", response_model=InstagramMessageReceipt)
async def send_message(payload: InstagramMessageRequest, request: Request) -> InstagramMessageReceipt:
    try:
        return await request.app.state.instagram_service.send_message(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
