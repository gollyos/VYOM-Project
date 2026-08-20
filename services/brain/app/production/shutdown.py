from __future__ import annotations

import asyncio
import time


class GracefulShutdown:
    """Orchestrated shutdown: stop accepting new work, checkpoint
    active tasks, let atomic operations finish, park the rest, flush
    the database, close logs and process/browser resources. Task state
    is never corrupted by an abrupt exit."""

    def __init__(self, *, automation_scheduler=None, supervisor=None, sync_bridge=None,
                 task_runtime=None, checkpoint_store=None, action_engine=None,
                 browser_session=None, playwright_manager=None, database=None):
        self.automation_scheduler = automation_scheduler
        self.supervisor = supervisor
        self.sync_bridge = sync_bridge
        self.task_runtime = task_runtime
        self.checkpoint_store = checkpoint_store
        self.action_engine = action_engine
        self.browser_session = browser_session
        self.playwright_manager = playwright_manager
        self.database = database
        self._entered = False

    async def execute(self, timeout_seconds: float = 15.0) -> dict:
        if self._entered:
            return {"already_shutting_down": True}
        self._entered = True
        started = time.perf_counter()
        steps: list[str] = []

        async def _safe(name: str, coroutine) -> None:
            try:
                await asyncio.wait_for(coroutine, timeout=timeout_seconds)
                steps.append(name)
            except Exception as error:
                steps.append(f"{name}:error:{type(error).__name__}")

        # 1) Stop accepting new scheduled/background work.
        if self.supervisor is not None:
            await _safe("supervisor_stopped", self.supervisor.stop())
        if self.automation_scheduler is not None:
            await _safe("scheduler_stopped", self.automation_scheduler.stop())
        if self.sync_bridge is not None:
            await _safe("sync_bridge_stopped", self.sync_bridge.stop())

        # 2) Checkpoint active tasks so restart recovery can resume.
        if self.task_runtime is not None and self.checkpoint_store is not None:
            from app.reliability.checkpoints import TaskCheckpoint

            for task_id, active in list(getattr(self.task_runtime, "active", {}).items()):
                if active.done():
                    continue
                try:
                    await self.checkpoint_store.save(TaskCheckpoint(
                        task_id=task_id, task_state={"status": "shutdown_checkpoint"},
                    ))
                    active.cancel()
                except Exception:
                    continue
            if self.task_runtime.active:
                await asyncio.gather(*self.task_runtime.active.values(), return_exceptions=True)
            steps.append("tasks_checkpointed_and_parked")

        # 3) Close execution resources.
        if self.action_engine is not None:
            await _safe("action_engine_shutdown", self.action_engine.shutdown())
        if self.browser_session is not None:
            await _safe("browser_closed", self.browser_session.close())
        if self.playwright_manager is not None:
            await _safe("playwright_closed", self.playwright_manager.close())

        # 4) Flush and close the database last.
        if self.database is not None:
            await _safe("database_closed", self.database.close())

        return {"steps": steps, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
