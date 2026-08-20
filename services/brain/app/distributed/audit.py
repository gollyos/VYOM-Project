from __future__ import annotations

from app.devices.schemas import utc_now


class DistributedAuditLog:
    """Append-only cross-device audit trail: which node performed
    which action for which task, with result and evidence references.
    Answers "Which device ran this?" from durable records."""

    def __init__(self, database):
        self.database = database

    async def record(
        self,
        action: str,
        *,
        node_id: str | None = None,
        task_id: str | None = None,
        result: str = "ok",
        evidence: str | None = None,
    ) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO distributed_audit (task_id, node_id, action, result, evidence, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, node_id, action, result, evidence, utc_now().isoformat()),
        )
        await self.database.require_connection().commit()

    async def for_task(self, task_id: str) -> list[dict]:
        cursor = await self.database.require_connection().execute(
            "SELECT task_id, node_id, action, result, evidence, recorded_at FROM distributed_audit "
            "WHERE task_id = ? ORDER BY recorded_at, id",
            (task_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def recent(self, limit: int = 100, since_iso: str | None = None) -> list[dict]:
        if since_iso:
            cursor = await self.database.require_connection().execute(
                "SELECT task_id, node_id, action, result, evidence, recorded_at FROM distributed_audit "
                "WHERE recorded_at >= ? ORDER BY recorded_at DESC LIMIT ?",
                (since_iso, limit),
            )
        else:
            cursor = await self.database.require_connection().execute(
                "SELECT task_id, node_id, action, result, evidence, recorded_at FROM distributed_audit "
                "ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in await cursor.fetchall()]
