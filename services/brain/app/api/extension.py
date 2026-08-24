from __future__ import annotations

import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/api/extension", tags=["extension"])
logger = logging.getLogger("vyom.browser_extension")


@router.get("/pairing")
async def get_pairing(request: Request) -> dict:
    """The token + endpoint the extension's popup needs to pair once.
    Idempotent: repeated calls return the SAME token until explicitly
    reset, so re-opening the popup never silently invalidates a working
    connection."""
    store = request.app.state.extension_pairing
    bridge = request.app.state.extension_bridge
    return {
        "token": store.get_or_create(),
        "ws_path": "/api/extension/ws",
        "connected": bridge.connected,
    }


@router.post("/pairing/reset")
async def reset_pairing(request: Request) -> dict:
    """Invalidate the current token (e.g. after a suspected leak) and
    issue a new one. Any already-connected extension is left alone until
    it next tries to reconnect with the old token."""
    store = request.app.state.extension_pairing
    return {"token": store.reset()}


@router.get("/status")
async def get_status(request: Request) -> dict:
    return {"connected": request.app.state.extension_bridge.connected}


@router.websocket("/ws")
async def extension_socket(websocket: WebSocket) -> None:
    """The one persistent connection a paired Chrome extension holds
    open. Every command VYOM issues to the real browser goes out over
    this socket; every reply comes back over it, matched by request id
    in ExtensionBridge.resolve()."""
    store = websocket.app.state.extension_pairing
    if not store.verify(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return
    bridge = websocket.app.state.extension_bridge
    await websocket.accept()
    await bridge.attach(websocket)
    logger.info("Chrome extension connected")
    try:
        while True:
            message = await websocket.receive_json()
            bridge.resolve(message)
    except WebSocketDisconnect:
        pass
    finally:
        await bridge.detach(websocket)
        logger.info("Chrome extension disconnected")
