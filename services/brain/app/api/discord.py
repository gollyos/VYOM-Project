from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.messaging.discord_schemas import DiscordConnectRequest, DiscordSendReceipt

router = APIRouter(prefix="/api/discord", tags=["discord"])


class SendMessagePayload(BaseModel):
    channel_id: str
    content: str


@router.post("/connect")
async def connect(payload: DiscordConnectRequest, request: Request) -> dict:
    """Connects via a bot token (Discord Developer Portal -> New
    Application -> Bot -> Copy Token) — no OAuth consent flow, matching
    Telegram's simplicity. Verifies by actually calling GET /users/@me
    before reporting success, same as Instagram's connect endpoint never
    trusting an unverified token."""
    provider = request.app.state.discord_provider
    provider.store_credentials(payload.bot_token)
    healthy, error = await provider.health()
    if not healthy:
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Discord connect failed")
    return {"status": "connected"}


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.discord_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/status")
async def status(request: Request) -> dict:
    healthy, error = await request.app.state.discord_provider.health()
    return {"connected": healthy, "detail": error}


@router.post("/send", response_model=DiscordSendReceipt)
async def send_message(payload: SendMessagePayload, request: Request) -> DiscordSendReceipt:
    try:
        return await request.app.state.discord_service.send(payload.channel_id, payload.content)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/guilds")
async def list_guilds(request: Request) -> dict:
    try:
        guilds = await request.app.state.discord_service.list_guilds()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"guilds": [guild.model_dump(mode="json") for guild in guilds]}
