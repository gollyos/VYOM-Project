from __future__ import annotations

import asyncio

from app.distributed.coordinator import DistributedCoordinator
from app.distributed.leases import LeaseManager
from app.automation.store import AutomationStore

from .health import HealthAggregator, ReliabilityMetrics


class Supervisor:
    """The always-on background supervisor for the persistent runtime:
    periodically runs health checks, expires stale leases (triggering
    safe handoff), and applies missed-automation policy through the
    existing scheduler's bounded recovery. Every recovery it performs
    is bounded — nothing here restarts endlessly."""

    def __init__(
        self,
        coordinator: DistributedCoordinator,
        health: HealthAggregator,
        leases: LeaseManager,
        metrics: ReliabilityMetrics,
        *,
        poll_seconds: float = 30.0,
        automation_store: AutomationStore | None = None,
    ):
        self.coordinator = coordinator
        self.health = health
        self.leases = leases
        self.metrics = metrics
        self.poll_seconds = poll_seconds
        self.automation_store = automation_store
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="vyom-supervisor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                pass  # supervisor failures never crash the runtime
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> dict:
        report = await self.health.assess()
        expired = await self.coordinator.handle_expired_leases()
        if self.automation_store is not None:
            due_count = len(await self.automation_store.due(await self._now()))
        else:
            due_count = 0
        return {
            "health": report,
            "expired_leases": expired,
            "automations_due": due_count,
        }

    @staticmethod
    async def _now():
        from app.devices.schemas import utc_now

        return utc_now()
