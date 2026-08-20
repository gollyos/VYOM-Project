from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.events import EventType


class RemoteDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: f"delivery_{uuid4().hex}")
    node_id: str
    kind: str
    payload: dict[str, Any]
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: datetime | None = None


class RemoteDeliveryStore:
    def __init__(self, database):
        self.database = database

    async def enqueue(self, node_id: str, kind: str, payload: dict[str, Any]) -> RemoteDelivery:
        delivery = RemoteDelivery(node_id=node_id, kind=kind, payload=payload)
        await self.database.require_connection().execute(
            "INSERT INTO remote_deliveries(delivery_id,node_id,status,delivery_json,created_at) VALUES (?,?,?,?,?)",
            (delivery.delivery_id, node_id, delivery.status, delivery.model_dump_json(), delivery.created_at.isoformat()),
        )
        await self.database.require_connection().commit()
        return delivery

    async def pending(self, node_id: str, limit: int = 50) -> list[RemoteDelivery]:
        rows = await (await self.database.require_connection().execute(
            "SELECT delivery_json FROM remote_deliveries WHERE node_id = ? AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?", (node_id, min(max(limit, 1), 100)),
        )).fetchall()
        return [RemoteDelivery.model_validate_json(row["delivery_json"]) for row in rows]

    async def acknowledge(self, node_id: str, delivery_id: str) -> RemoteDelivery:
        row = await (await self.database.require_connection().execute(
            "SELECT delivery_json FROM remote_deliveries WHERE delivery_id = ? AND node_id = ?",
            (delivery_id, node_id),
        )).fetchone()
        if row is None:
            raise KeyError(delivery_id)
        delivery = RemoteDelivery.model_validate_json(row["delivery_json"])
        delivery.status = "acknowledged"
        delivery.acknowledged_at = datetime.now(timezone.utc)
        await self.database.require_connection().execute(
            "UPDATE remote_deliveries SET status = ?, delivery_json = ?, acknowledged_at = ? WHERE delivery_id = ?",
            (delivery.status, delivery.model_dump_json(), delivery.acknowledged_at.isoformat(), delivery.delivery_id),
        )
        await self.database.require_connection().commit()
        return delivery


class RemoteDeliveryBridge:
    TERMINAL = {EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED}

    def __init__(self, event_bus, task_store, delivery_store: RemoteDeliveryStore):
        self.event_bus = event_bus
        self.task_store = task_store
        self.delivery_store = delivery_store
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop(), name="vyom-remote-delivery")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    async def handle(self, event) -> RemoteDelivery | None:
        if event.type not in self.TERMINAL:
            return None
        task = await self.task_store.get(event.task_id)
        if task is None or not task.source.startswith("remote:"):
            return None
        node_id = task.source.split(":", 1)[1]
        result = task.result
        return await self.delivery_store.enqueue(node_id, "task_result", {
            "task_id": task.id, "status": task.status.value,
            "summary": (result.response if result else None) or event.human_readable_message,
            "evidence": result.evidence if result else [],
            "completed_at": (task.completed_at or event.timestamp).isoformat(),
        })

    async def _loop(self) -> None:
        async for event in self.event_bus.subscribe():
            try:
                await self.handle(event)
            except Exception:
                logging.getLogger("vyom.remote").exception(
                    "Remote result delivery failed for event %s", event.event_id,
                )
