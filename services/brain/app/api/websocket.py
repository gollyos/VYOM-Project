import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["events"])


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    """Live event stream with reconnect replay and keepalive heartbeats.

    A disconnect used to silently DROP every event published while the
    client was away - "task gayab" after a network blip. A reconnecting
    client passes `since=<last event_id>`; everything published after
    that cursor is replayed before the live stream continues. Subscribe
    BEFORE snapshotting history so nothing published in the gap is lost,
    and skip ids already replayed when draining the live queue.
    Periodic 15s heartbeats keep the connection active during idle periods."""
    await websocket.accept()
    task_filter = websocket.query_params.get("task_id")
    since_event_id = websocket.query_params.get("since")
    bus = websocket.app.state.event_bus
    queue, unregister = bus.register()
    replayed: set[str] = set()

    async def _inbound_listener() -> None:
        """Listens for client pings or control messages."""
        try:
            while True:
                data = await websocket.receive_text()
                if data.strip().lower() == "ping":
                    await websocket.send_text("pong")
        except (WebSocketDisconnect, Exception):
            pass

    inbound_task = asyncio.create_task(_inbound_listener())

    try:
        for event in bus.history_after(since_event_id):
            if task_filter and event.task_id != task_filter:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
            replayed.add(event.event_id)
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                if event.event_id in replayed:
                    continue
                if task_filter and event.task_id != task_filter:
                    continue
                await websocket.send_json(event.model_dump(mode="json"))
            except asyncio.TimeoutError:
                # Dispatch keepalive heartbeat so idle WebSocket doesn't drop
                await websocket.send_json({
                    "schema_version": 1,
                    "type": "heartbeat",
                    "message": "keepalive",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
    except WebSocketDisconnect:
        return
    finally:
        inbound_task.cancel()
        unregister()

