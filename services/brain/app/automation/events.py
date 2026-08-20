from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.schemas.events import BrainEvent

from .scheduler import AutomationScheduler
from .store import AutomationStore


class AutomationEventEngine:
    """Durable conditional automation bridge over the central EventBus."""

    def __init__(self, store: AutomationStore, scheduler: AutomationScheduler, event_bus):
        self.store = store
        self.scheduler = scheduler
        self.event_bus = event_bus
        self._worker: asyncio.Task | None = None
        self._owned_tasks: deque[str] = deque(maxlen=500)

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop(), name="vyom-automation-events")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    async def handle(self, event: BrainEvent) -> list:
        if event.task_id in self._owned_tasks:
            return []
        completed = []
        now = datetime.now(timezone.utc)
        for automation in await self.store.conditional():
            condition = automation.condition or {}
            if condition.get("event_type") != event.type.value:
                continue
            if not self._matches(condition.get("filters", {}), event):
                continue
            debounce = float(condition.get("debounce_seconds", 0))
            if automation.last_run_at and (now - automation.last_run_at).total_seconds() < debounce:
                continue
            trigger = {"event_id": event.event_id, "event_type": event.type.value, "task_id": event.task_id}
            run = await self.scheduler.run_automation(
                automation, event.event_id, current=now, advance=False, trigger=trigger,
            )
            if run is not None:
                task_id = run.result.get("task_id")
                if task_id:
                    self._owned_tasks.append(str(task_id))
                completed.append(run)
        return completed

    @staticmethod
    def _matches(filters: dict[str, Any], event: BrainEvent) -> bool:
        available = {"task_id": event.task_id, "message": event.human_readable_message,
                     **event.structured_payload}
        return all(available.get(key) == expected for key, expected in filters.items())

    async def _loop(self) -> None:
        async for event in self.event_bus.subscribe():
            try:
                await self.handle(event)
            except Exception:
                logging.getLogger("vyom.automation").exception(
                    "Conditional automation event handling failed for %s", event.event_id,
                )
