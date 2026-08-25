from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.twitter.schemas import TwitterConnectRequest, TwitterPostReceipt, TwitterPostRequest

router = APIRouter(prefix="/api/twitter", tags=["twitter"])


@router.post("/connect")
async def connect(payload: TwitterConnectRequest, request: Request) -> dict:
    """Connects via a single OAuth 2.0 User Context access token minted
    for yourself in the X Developer Portal — no full consent-screen flow
    needed for posting to your own account. Verifies by actually
    querying the account before reporting success."""
    provider = request.app.state.twitter_provider
    provider.store_credentials(payload.access_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Twitter connect failed")
    return {"status": "connected"}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.twitter_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.twitter_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/post", response_model=TwitterPostReceipt)
async def post_tweet(payload: TwitterPostRequest, request: Request) -> TwitterPostReceipt:
    try:
        return await request.app.state.twitter_service.post(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
