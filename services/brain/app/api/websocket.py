from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter(tags=["events"])


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    task_filter = websocket.query_params.get("task_id")
    try:
        async for event in websocket.app.state.event_bus.subscribe():
            if task_filter and event.task_id != task_filter:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        return

