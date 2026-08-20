from __future__ import annotations

import asyncio

from app.runtime.event_bus import EventBus
from app.schemas.events import EventType

from .journal import SyncJournal
from .schemas import SyncEntity

# Brain events that carry shared cross-device state and therefore flow
# into the sync journal. Everything else stays node-local.
EVENT_ENTITY_MAP: dict[EventType, SyncEntity] = {
    EventType.TASK_CREATED: SyncEntity.TASK,
    EventType.TASK_COMPLETED: SyncEntity.TASK,
    EventType.TASK_FAILED: SyncEntity.TASK,
    EventType.TASK_CANCELLED: SyncEntity.TASK,
    EventType.TASK_PROGRESS: SyncEntity.TASK,
    EventType.TASK_DISPATCHED: SyncEntity.TASK,
    EventType.APPROVAL_REQUIRED: SyncEntity.APPROVAL,
    EventType.AUTOMATION_CREATED: SyncEntity.AUTOMATION,
    EventType.AUTOMATION_STARTED: SyncEntity.AUTOMATION,
    EventType.AUTOMATION_COMPLETED: SyncEntity.AUTOMATION,
    EventType.AUTOMATION_FAILED: SyncEntity.AUTOMATION,
    EventType.AUTOMATION_PAUSED: SyncEntity.AUTOMATION,
    EventType.AUTOMATION_RESUMED: SyncEntity.AUTOMATION,
    EventType.MOBILE_APPROVAL_RECEIVED: SyncEntity.APPROVAL,
    EventType.REMOTE_COMMAND_RECEIVED: SyncEntity.DEVICE_STATE,
    EventType.NODE_ONLINE: SyncEntity.DEVICE_STATE,
    EventType.NODE_OFFLINE: SyncEntity.DEVICE_STATE,
    EventType.NODE_REGISTERED: SyncEntity.DEVICE_STATE,
    EventType.NODE_REVOKED: SyncEntity.DEVICE_STATE,
}


class SyncEventBridge:
    """Streams selected Brain events into the append-only sync journal
    so every connected device can pull shared-state changes since its
    last sequence number."""

    def __init__(self, event_bus: EventBus, journal: SyncJournal):
        self.event_bus = event_bus
        self.journal = journal
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="vyom-sync-bridge")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        subscriber = self.event_bus.subscribe()
        try:
            async for event in subscriber:
                entity = EVENT_ENTITY_MAP.get(event.type)
                if entity is None:
                    continue
                await self.journal.record_state_change(
                    entity,
                    event.task_id,
                    {"event": event.type.value, "message": event.human_readable_message, **event.structured_payload},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # the bridge must never take the runtime down
