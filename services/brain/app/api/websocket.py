from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["events"])


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    """Live event stream with reconnect replay.

    A disconnect used to silently DROP every event published while the
    client was away - "task gayab" after a network blip. A reconnecting
    client passes `since=<last event_id>`; everything published after
    that cursor is replayed before the live stream continues. Subscribe
    BEFORE snapshotting history so nothing published in the gap is lost,
    and skip ids already replayed when draining the live queue."""
    await websocket.accept()
    task_filter = websocket.query_params.get("task_id")
    since_event_id = websocket.query_params.get("since")
    bus = websocket.app.state.event_bus
    queue, unregister = bus.register()
    replayed: set[str] = set()
    try:
        for event in bus.history_after(since_event_id):
            if task_filter and event.task_id != task_filter:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
            replayed.add(event.event_id)
        while True:
            event = await queue.get()
            if event.event_id in replayed:
                continue
            if task_filter and event.task_id != task_filter:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        return
    finally:
        unregister()
