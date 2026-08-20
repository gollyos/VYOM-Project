from __future__ import annotations

from datetime import timedelta

from app.devices.schemas import utc_now

from .schemas import TaskLease


class LeaseError(Exception):
    pass


class LeaseManager:
    """SQLite-backed task leases. Exactly one node may hold a lease on
    a task at a time; a lease that stops heartbeating expires, and the
    coordinator then decides whether a safe retry/handoff is possible.
    Consequential tasks additionally reserve through the idempotency
    table so a failover can never double-execute them."""

    def __init__(self, database, default_ttl_seconds: int = 120):
        self.database = database
        self.default_ttl_seconds = default_ttl_seconds

    async def acquire(self, task_id: str, node_id: str, *, ttl_seconds: int | None = None) -> TaskLease:
        existing = await self.get(task_id)
        now = utc_now()
        if existing is not None and existing.node_id != node_id and existing.expires_at > now:
            raise LeaseError(
                f"Task {task_id} is leased by node {existing.node_id} until {existing.expires_at.isoformat()}"
            )
        effective_ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        lease = TaskLease(
            task_id=task_id,
            node_id=node_id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=effective_ttl),
            heartbeat_at=now,
        )
        await self._save(lease)
        return lease

    async def heartbeat(self, task_id: str, node_id: str, *, extend_seconds: int | None = None) -> TaskLease:
        lease = await self.get(task_id)
        if lease is None or lease.node_id != node_id:
            raise LeaseError(f"Node {node_id} does not hold a lease on task {task_id}")
        now = utc_now()
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=extend_seconds or self.default_ttl_seconds)
        await self._save(lease)
        return lease

    async def release(self, task_id: str, node_id: str) -> None:
        lease = await self.get(task_id)
        if lease is not None and lease.node_id == node_id:
            await self.database.require_connection().execute(
                "DELETE FROM task_leases WHERE task_id = ?", (task_id,)
            )
            await self.database.require_connection().commit()

    async def get(self, task_id: str) -> TaskLease | None:
        cursor = await self.database.require_connection().execute(
            "SELECT lease_json FROM task_leases WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return None if row is None else TaskLease.model_validate_json(row["lease_json"])

    async def expired(self, now=None) -> list[TaskLease]:
        now = now or utc_now()
        cursor = await self.database.require_connection().execute(
            "SELECT lease_json FROM task_leases WHERE expires_at <= ? ORDER BY acquired_at",
            (now.isoformat(),),
        )
        return [TaskLease.model_validate_json(row["lease_json"]) for row in await cursor.fetchall()]

    async def _save(self, lease: TaskLease) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO task_leases (task_id, node_id, lease_id, acquired_at, expires_at, heartbeat_at, lease_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                node_id = excluded.node_id,
                lease_id = excluded.lease_id,
                acquired_at = excluded.acquired_at,
                expires_at = excluded.expires_at,
                heartbeat_at = excluded.heartbeat_at,
                lease_json = excluded.lease_json
            """,
            (
                lease.task_id,
                lease.node_id,
                lease.lease_id,
                lease.acquired_at.isoformat(),
                lease.expires_at.isoformat(),
                lease.heartbeat_at.isoformat(),
                lease.model_dump_json(),
            ),
        )
        await self.database.require_connection().commit()
