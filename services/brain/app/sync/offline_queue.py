from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.devices.schemas import utc_now
from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType
from app.security.permission_engine import PermissionEngine
from app.schemas.approvals import PermissionLevel

from .schemas import SyncRecord, SyncEntity

# Consequential commands expire fast: an offline "send email" must not
# fire eight hours later merely because the network returned.
CONSEQUENTIAL_TTL_SECONDS = 300
SAFE_TTL_SECONDS = 24 * 3600


class OfflineCommandQueue:
    """Client-side queue for commands created while offline. Harmless
    commands (status queries, notes, reminders) wait up to a day;
    consequential commands (L2/L3) expire within minutes and must be
    reconfirmed after reconnect — an expired command is reported, never
    silently executed."""

    def __init__(self, database, event_bus: EventBus | None = None, permission_engine: PermissionEngine | None = None):
        self.database = database
        self.event_bus = event_bus
        self.permission_engine = permission_engine or PermissionEngine()

    async def enqueue(self, command: dict) -> dict:
        command_id = command.get("id") or f"offcmd_{uuid4().hex}"
        level = self.permission_engine.classify(str(command.get("command", "")))
        consequential = level in (PermissionLevel.L2, PermissionLevel.L3)
        ttl = CONSEQUENTIAL_TTL_SECONDS if consequential else SAFE_TTL_SECONDS
        record = {
            "id": command_id,
            "command": command.get("command", ""),
            "risk": level.value,
            "consequential": consequential,
            "requires_reconfirmation": consequential,
            "payload": command.get("payload", {}),
            "source_node": command.get("source_node", "mobile"),
        }
        now = utc_now()
        await self.database.require_connection().execute(
            """
            INSERT INTO offline_commands (id, status, expires_at, command_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET status = excluded.status, expires_at = excluded.expires_at,
                command_json = excluded.command_json
            """,
            (
                command_id, "queued", (now + timedelta(seconds=ttl)).isoformat(),
                SyncRecord(entity=SyncEntity.TASK, entity_id=command_id, payload=record).model_dump_json(),
                now.isoformat(),
            ),
        )
        await self.database.require_connection().commit()
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id=command_id, type=EventType.OFFLINE_COMMAND_QUEUED,
                human_readable_message="Offline command queued",
                structured_payload={"id": command_id, "expires_in_seconds": ttl, "consequential": consequential},
            ))
        return {**record, "expires_in_seconds": ttl}

    async def pending(self) -> list[dict]:
        cursor = await self.database.require_connection().execute(
            "SELECT command_json FROM offline_commands WHERE status = 'queued' ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [SyncRecord.model_validate_json(row["command_json"]).payload for row in rows]

    async def submit_due(self, submitter=None) -> list[dict]:
        """Submit queued commands on reconnect. `submitter` is an async
        callable(command_record) -> dict. Expired consequential commands
        are marked expired and returned with executed=False — never
        executed. Each queued command submits exactly once."""
        results: list[dict] = []
        now = utc_now()
        for record in await self.pending():
            cursor = await self.database.require_connection().execute(
                "SELECT expires_at, status FROM offline_commands WHERE id = ?", (record["id"],)
            )
            row = await cursor.fetchone()
            if row is None:
                continue
            expires_at = row["expires_at"]
            expired = now.isoformat() > expires_at
            if expired:
                await self._set_status(record["id"], "expired")
                if self.event_bus is not None:
                    await self.event_bus.publish(BrainEvent(
                        task_id=record["id"], type=EventType.OFFLINE_COMMAND_EXPIRED,
                        human_readable_message="Offline command expired before reconnect",
                        structured_payload={"id": record["id"], "consequential": record["consequential"]},
                    ))
                results.append({**record, "executed": False, "reason": "expired"})
                continue
            if record.get("requires_reconfirmation"):
                results.append({**record, "executed": False, "reason": "reconfirmation_required"})
                continue
            outcome = {"executed": True, "result": None}
            if submitter is not None:
                submitted = submitter(record)
                if hasattr(submitted, "__await__"):
                    submitted = await submitted
                outcome["result"] = submitted
            await self._set_status(record["id"], "submitted" if outcome["executed"] else "skipped")
            results.append({**record, **outcome})
        return results

    async def _set_status(self, command_id: str, status: str) -> None:
        await self.database.require_connection().execute(
            "UPDATE offline_commands SET status = ?, submitted_at = ? WHERE id = ?",
            (status, utc_now().isoformat() if status != "queued" else None, command_id),
        )
        await self.database.require_connection().commit()
