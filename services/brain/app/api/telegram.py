from __future__ import annotations

import base64
import io

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


class SendMessagePayload(BaseModel):
    chat_id: str
    text: str
    parse_mode: str | None = None


class ConnectTokenPayload(BaseModel):
    bot_token: str


@router.post("/connect-token")
async def connect_with_token(payload: ConnectTokenPayload, request: Request) -> dict:
    """Self-service Telegram connect: paste a @BotFather bot token
    directly (no TELEGRAM_BOT_TOKEN env var edit needed). Verifies the
    token against a real getMe call before storing it — never reports
    success on a bad token. Restart the Brain to activate it (read once
    at startup, matching GOOGLE_OAUTH_CLIENT_ID/_SECRET's pattern)."""
    from app.messaging.telegram_provider import RealTelegramProvider

    provider = RealTelegramProvider(payload.bot_token)
    healthy, error = await provider.health()
    if not healthy:
        raise HTTPException(status_code=401, detail=error or "Telegram bot token rejected")
    request.app.state.secret_vault.set("token:telegram", payload.bot_token.encode("utf-8"))
    return {"status": "connected", "note": "Restart the Brain to activate this bot token."}


@router.get("/connect")
async def get_connect_info(request: Request) -> dict:
    """Returns the bot's t.me link AND a scannable QR code encoding that
    same link (base64 PNG data URL) — the same 'scan to connect' UX as
    Hermes/WhatsApp Web: the user scans it with their phone's camera (or
    Telegram's in-app QR scanner), which opens a chat with VYOM's bot, and
    sending it any message completes the connection (VYOM then knows their
    chat_id from that message via poll_and_record())."""
    provider = request.app.state.telegram_provider
    healthy, error = await provider.health()
    if not healthy:
        raise HTTPException(status_code=503, detail=error or "Telegram bot token is not configured")
    username = await provider.get_bot_username()
    link = f"https://t.me/{username}"

    import qrcode

    img = qrcode.make(link)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"bot_username": username, "connect_url": link, "qr_code_data_url": qr_data_url}


@router.post("/send")
async def send_message(payload: SendMessagePayload, request: Request) -> dict:
    service = request.app.state.telegram_service
    try:
        receipt = await service.send(payload.chat_id, payload.text, parse_mode=payload.parse_mode)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return receipt.model_dump(mode="json")


@router.post("/poll")
async def poll_updates(request: Request, limit: int = 20) -> dict:
    """Fetch new inbound messages and record any new chat_ids into the
    directory. Call this periodically (or on-demand before listing known
    chats) — Telegram has no 'list all chats' endpoint, so this IS how VYOM
    builds up who it can message."""
    service = request.app.state.telegram_service
    try:
        messages = await service.poll_and_record(limit=limit)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"messages": [message.model_dump(mode="json") for message in messages]}


@router.get("/chats")
async def list_chats(request: Request) -> dict:
    service = request.app.state.telegram_service
    chats = await service.list_known_chats()
    return {"chats": [chat.model_dump(mode="json") for chat in chats]}
