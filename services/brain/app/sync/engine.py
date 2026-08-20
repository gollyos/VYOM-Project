from __future__ import annotations

from datetime import datetime

from app.devices.schemas import utc_now
from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType

from .conflict_resolver import ConflictResolver
from .journal import SyncJournal
from .schemas import FreshnessView, SyncEntity, SyncRecord

# Freshness windows per entity (seconds). A view older than its window
# is flagged stale and must never be presented as live state.
DEFAULT_FRESHNESS_SECONDS = 30
FRESHNESS_WINDOWS: dict[SyncEntity, float] = {
    SyncEntity.TASK: 15,
    SyncEntity.TASK_EVENT: 15,
    SyncEntity.APPROVAL: 20,
    SyncEntity.NOTIFICATION: 60,
    SyncEntity.DEVICE_STATE: 30,
    SyncEntity.AGENT: 120,
    SyncEntity.AUTOMATION: 120,
    SyncEntity.GOAL: 300,
    SyncEntity.MEMORY_METADATA: 300,
}


class SyncEngine:
    """Local-first sync over the append-only journal. `apply` records
    local mutations, `pull` fetches records from a peer journal since a
    sequence number, `push` offers local records to a peer. Conflict
    handling always goes through the explicit ConflictResolver."""

    def __init__(self, journal: SyncJournal, resolver: ConflictResolver, event_bus: EventBus | None = None):
        self.journal = journal
        self.resolver = resolver
        self.event_bus = event_bus

    async def apply(self, entity: SyncEntity, entity_id: str, payload: dict, current: dict | None = None) -> SyncRecord:
        resolved, _conflict = await self.resolver.detect_and_resolve(
            SyncRecord(entity=entity, entity_id=entity_id, payload=payload), current,
        )
        return await self.journal.record_state_change(entity, entity_id, resolved)

    async def pull(self, peer: SyncJournal, since_seq: int, applier=None) -> dict:
        """Pull records from a peer journal and apply them locally.
        Returns applied records and detected conflicts."""
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id="system", type=EventType.SYNC_STARTED,
                human_readable_message="Sync pull started",
                structured_payload={"peer": peer.origin_node, "since": since_seq},
            ))
        records = await peer.since(since_seq)
        conflicts = []
        applied = []
        for record in records:
            current = None
            if applier is not None:
                supplied = applier(record)
                if hasattr(supplied, "__await__"):
                    supplied = await supplied
                current = supplied
            resolved, conflict = await self.resolver.detect_and_resolve(record, current)
            applied.append({**resolved, "entity": record.entity.value, "entity_id": record.entity_id})
            if conflict is not None:
                conflicts.append(conflict.model_dump())
                if self.event_bus is not None:
                    await self.event_bus.publish(BrainEvent(
                        task_id=record.entity_id, type=EventType.SYNC_CONFLICT,
                        human_readable_message=f"Sync conflict on {record.entity.value}/{record.entity_id}",
                        structured_payload={"resolution": conflict.resolution},
                    ))
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id="system", type=EventType.SYNC_COMPLETED,
                human_readable_message=f"Sync pull applied {len(applied)} records",
                structured_payload={"applied": len(applied), "conflicts": len(conflicts)},
            ))
        return {"applied": applied, "conflicts": conflicts, "pulled": len(records)}

    async def freshness(self, entity: SyncEntity, payload: dict, as_of: datetime | None = None) -> FreshnessView:
        as_of = as_of or utc_now()
        age = (utc_now() - as_of).total_seconds()
        window = FRESHNESS_WINDOWS.get(entity, DEFAULT_FRESHNESS_SECONDS)
        return FreshnessView(entity=entity, payload=payload, as_of=as_of, stale=age > window, age_seconds=max(age, 0.0))
