from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.whatsapp.schemas import WhatsAppSendRequest, WhatsAppStatus

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.post("/connect", response_model=WhatsAppStatus)
async def connect(request: Request) -> WhatsAppStatus:
    """Starts the real whatsapp-web.js session. Returns immediately with
    state='starting' — poll GET /api/whatsapp/status until state
    becomes 'qr_pending' (render qr_data_url as an <img>) then 'ready'
    once the phone scan completes."""
    connector = request.app.state.whatsapp_connector
    try:
        return await connector.start()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/status", response_model=WhatsAppStatus)
async def status(request: Request) -> WhatsAppStatus:
    return request.app.state.whatsapp_connector.status


@router.post("/disconnect")
async def disconnect(request: Request) -> dict:
    await request.app.state.whatsapp_connector.disconnect()
    return {"status": "disconnected"}


@router.post("/send")
async def send_message(payload: WhatsAppSendRequest, request: Request) -> dict:
    connector = request.app.state.whatsapp_connector
    healthy, error = await connector.health()
    if not healthy:
        raise HTTPException(status_code=503, detail=error or "WhatsApp is not connected")
    try:
        await connector.send_message(payload.to, payload.body)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"status": "sent", "to": payload.to}
