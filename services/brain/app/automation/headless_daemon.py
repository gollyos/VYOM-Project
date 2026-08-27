"""
24/7 VPS Headless Daemon & Autonomous Cron Engine for VYOM.
Allows running VYOM Brain continuously on a VPS / Cloud Server without a GUI,
executing background routines, scheduled cron jobs, social inboxes, and paper trading monitors.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    id: str
    name: str
    interval_seconds: int
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run_at: str | None = None
    run_count: int = 0


class HeadlessServerDaemon:
    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or Path("services/brain/data/headless_daemon_state.json")
        self.jobs: dict[str, CronJob] = {}
        self.handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self.started_at: str | None = None
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                for item in data.get("jobs", []):
                    job = CronJob(**item)
                    self.jobs[job.id] = job
            except Exception:
                self.jobs = {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "running" if self._running else "stopped",
            "started_at": self.started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": [asdict(j) for j in self.jobs.values()],
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_handler(self, action: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self.handlers[action] = handler

    def add_job(
        self,
        job_id: str,
        name: str,
        interval_seconds: int,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> CronJob:
        job = CronJob(
            id=job_id,
            name=name,
            interval_seconds=max(1, interval_seconds),
            action=action,
            params=params or {},
        )
        self.jobs[job_id] = job
        self._save_state()
        return job

    async def execute_job(self, job: CronJob) -> Any:
        handler = self.handlers.get(job.action)
        if not handler:
            return {"status": "skipped", "reason": f"No handler registered for {job.action}"}

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(job.params)
            else:
                result = handler(job.params)
            job.run_count += 1
            job.last_run_at = datetime.now(timezone.utc).isoformat()
            self._save_state()
            return result
        except Exception as err:
            logger.error(f"CronJob {job.id} failed: {err}")
            return {"status": "failed", "error": str(err)}

    async def _daemon_loop(self) -> None:
        while self._running:
            now = datetime.now(timezone.utc)
            for job in list(self.jobs.values()):
                if not job.enabled:
                    continue

                should_run = False
                if job.last_run_at is None:
                    should_run = True
                else:
                    try:
                        last_run = datetime.fromisoformat(job.last_run_at)
                        if (now - last_run).total_seconds() >= job.interval_seconds:
                            should_run = True
                    except ValueError:
                        should_run = True

                if should_run:
                    asyncio.create_task(self.execute_job(job))

            await asyncio.sleep(1)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._save_state()
        self._loop_task = asyncio.create_task(self._daemon_loop())

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
            self._loop_task = None
        self._save_state()
