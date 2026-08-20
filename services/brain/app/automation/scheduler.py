from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .schemas import Automation, AutomationRun, AutomationStatus
from .store import AutomationStore


AutomationAction = Callable[[Automation], Awaitable[dict]]


class AutomationScheduler:
    def __init__(self, store: AutomationStore, action: AutomationAction, *, poll_seconds: float = 5, recovery_limit: int = 10) -> None:
        self.store = store
        self.action = action
        self.poll_seconds = max(0.1, poll_seconds)
        self.recovery_limit = min(max(recovery_limit, 1), 25)
        self._worker: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._stop.clear()
            self._worker = asyncio.create_task(self._loop(), name="vyom-automation-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    async def tick(self, now: datetime | None = None) -> list[AutomationRun]:
        current = now or datetime.now(timezone.utc)
        completed: list[AutomationRun] = []
        for automation in await self.store.due(current, self.recovery_limit):
            if await self.store.runs_today(automation.id, current) >= automation.budget.max_runs_per_day:
                automation.status = AutomationStatus.PAUSED
                await self.store.save(automation)
                continue
            slot = automation.next_run_at or current
            digest = hashlib.sha256(f"{automation.id}:{slot.isoformat()}".encode()).hexdigest()[:24]
            run = AutomationRun(automation_id=automation.id, idempotency_key=f"{automation.id}:{digest}")
            if not await self.store.begin_run(run):
                continue
            try:
                run.result = await asyncio.wait_for(self.action(automation), timeout=automation.budget.max_runtime_seconds)
                if run.result.get("awaiting_approval"):
                    # The scheduled event successfully created an owned
                    # Brain task, but the real-world effect is not complete.
                    # Pause this automation until the user resolves the
                    # per-run approval; never label it completed or enqueue
                    # another occurrence over the top of it.
                    run.status = "waiting_approval"
                    automation.status = AutomationStatus.PAUSED
                else:
                    run.status = "completed"
                    automation.advance(current)
            except Exception as error:
                run.status = "failed"
                run.error = str(error)
                automation.status = AutomationStatus.PAUSED
            run.completed_at = datetime.now(timezone.utc)
            await self.store.finish_run(run)
            await self.store.save(automation)
            completed.append(run)
        return completed

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass
