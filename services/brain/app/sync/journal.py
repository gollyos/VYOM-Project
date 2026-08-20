from __future__ import annotations

from app.devices.schemas import utc_now

from .schemas import SyncAction, SyncEntity, SyncRecord


class SyncJournal:
    """Append-oriented, monotonically sequenced event journal. Nodes
    reconcile offline changes by pulling records `since(seq)`; the
    journal never mutates history, which is what makes offline replay
    and conflict detection deterministic."""

    def __init__(self, database, origin_node: str = "brain-local"):
        self.database = database
        self.origin_node = origin_node

    async def append(self, record: SyncRecord) -> SyncRecord:
        record.origin_node = record.origin_node or self.origin_node
        cursor = await self.database.require_connection().execute(
            """
            INSERT INTO sync_journal (entity, entity_id, action, origin_node, payload_json, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.entity.value,
                record.entity_id,
                record.action.value,
                record.origin_node,
                record.model_dump_json(),
                record.occurred_at.isoformat(),
            ),
        )
        await self.database.require_connection().commit()
        record.seq = cursor.lastrowid
        return record

    async def since(self, seq: int, limit: int = 500) -> list[SyncRecord]:
        cursor = await self.database.require_connection().execute(
            "SELECT payload_json FROM sync_journal WHERE seq > ? ORDER BY seq LIMIT ?",
            (seq, limit),
        )
        return [SyncRecord.model_validate_json(row["payload_json"]) for row in await cursor.fetchall()]

    async def latest_seq(self) -> int:
        cursor = await self.database.require_connection().execute(
            "SELECT COALESCE(MAX(seq), 0) AS latest FROM sync_journal"
        )
        row = await cursor.fetchone()
        return int(row["latest"])

    async def record_state_change(
        self, entity: SyncEntity, entity_id: str, payload: dict, action: SyncAction = SyncAction.STATE,
    ) -> SyncRecord:
        return await self.append(SyncRecord(
            entity=entity, entity_id=entity_id, action=action, payload=payload,
            origin_node=self.origin_node, occurred_at=utc_now(),
        ))
