from __future__ import annotations

import json

from app.devices.schemas import utc_now

from .leases import LeaseManager


class OwnershipError(Exception):
    pass


class TaskOwnershipRegistry:
    """Tracks which node owns a task and guards consequential actions
    with durable idempotency records. A node failover re-executing a
    consequential action must find the idempotency record and skip —
    this is the no-double-send guarantee for email/booking/payment
    style workloads."""

    def __init__(self, database, leases: LeaseManager):
        self.database = database
        self.leases = leases

    async def owner_of(self, task_id: str) -> str | None:
        lease = await self.leases.get(task_id)
        return lease.node_id if lease else None

    async def begin_consequential(self, task_id: str, node_id: str, action_key: str) -> bool:
        """Reserve a consequential action key. Returns True when this
        caller is the first to reserve it; False means the action was
        already performed or reserved elsewhere and must be skipped."""
        try:
            await self.database.require_connection().execute(
                """
                INSERT INTO idempotency_records (action_key, task_id, node_id, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (action_key, task_id, node_id, json.dumps({"state": "reserved"}), utc_now().isoformat()),
            )
            await self.database.require_connection().commit()
            return True
        except Exception:
            return False

    async def complete_consequential(self, action_key: str, result: dict) -> None:
        await self.database.require_connection().execute(
            "UPDATE idempotency_records SET result_json = ? WHERE action_key = ?",
            (json.dumps({"state": "completed", "result": result}), action_key),
        )
        await self.database.require_connection().commit()

    async def was_executed(self, action_key: str) -> bool:
        cursor = await self.database.require_connection().execute(
            "SELECT result_json FROM idempotency_records WHERE action_key = ?", (action_key,)
        )
        row = await cursor.fetchone()
        return row is not None
