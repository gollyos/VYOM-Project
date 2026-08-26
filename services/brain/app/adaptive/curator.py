"""VYOM Curator - idle-triggered background self-review, mirroring the
Hermes CLI's curator.py pattern (background skill/lesson maintenance
that runs when the agent is idle, never blocking the live session).

Unlike Hermes's curator (which reviews agent-created SKILL.md files),
VYOM's curator reviews VYOM's own structured adaptive state:
  - knowledge/service.py's per-domain wiki lint (contradicted / stale /
    low-confidence / orphan facts) - the Karpathy-wiki audit that
    already existed as an on-demand API, now also runs proactively.
  - the automation store for automations that have failed repeatedly
    (a signal worth surfacing, not silently letting fail forever).

Same invariants as Hermes's curator:
  - Idle-triggered, not a fixed-interval cron - runs only when nothing
    is actively happening.
  - Never destroys anything - findings are recorded to curator_runs and
    a BrainEvent is emitted; nothing is auto-deleted or auto-modified.
  - Runs in its own asyncio task, isolated from the live task runtime -
    a slow or failing curator pass never blocks a real user task.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.schemas.events import BrainEvent, EventType

logger = logging.getLogger(__name__)

DEFAULT_MIN_IDLE_MINUTES = 30
DEFAULT_INTERVAL_HOURS = 24
DEFAULT_POLL_SECONDS = 300  # check idle state every 5 minutes


class CuratorRunStore:
    """Persists one row per curator run to curator_runs, mirroring how
    automation_runs records automation history - the run log is real,
    queryable data, not just a log line that vanishes on restart."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def record(self, *, status: str, summary: dict) -> str:
        import json

        connection = self.database.require_connection()
        run_id = f"curator_{uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        await connection.execute(
            "INSERT INTO curator_runs(id, started_at, completed_at, status, summary_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, now, now, status, json.dumps(summary)),
        )
        await connection.commit()
        return run_id

    async def last_run_at(self) -> datetime | None:
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT started_at FROM curator_runs ORDER BY started_at DESC LIMIT 1"
        )).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["started_at"])

    async def recent(self, limit: int = 10) -> list[dict]:
        import json

        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT id, started_at, completed_at, status, summary_json FROM curator_runs "
            "ORDER BY started_at DESC LIMIT ?", (limit,),
        )).fetchall()
        return [
            {
                "id": row["id"], "started_at": row["started_at"], "completed_at": row["completed_at"],
                "status": row["status"], "summary": json.loads(row["summary_json"]),
            }
            for row in rows
        ]


class Curator:
    """Background idle-triggered self-review loop."""

    def __init__(
        self,
        *,
        task_store: TaskStore,
        run_store: CuratorRunStore,
        knowledge_service=None,
        automation_store=None,
        conversation_store=None,
        dialectic_reasoner=None,
        event_bus=None,
        min_idle_minutes: float = DEFAULT_MIN_IDLE_MINUTES,
        interval_hours: float = DEFAULT_INTERVAL_HOURS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self.task_store = task_store
        self.run_store = run_store
        self.knowledge_service = knowledge_service
        self.automation_store = automation_store
        self.conversation_store = conversation_store
        self.dialectic_reasoner = dialectic_reasoner
        self.event_bus = event_bus
        self.min_idle_minutes = min_idle_minutes
        self.interval_hours = interval_hours
        self.poll_seconds = max(5.0, poll_seconds)
        self._worker: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._stop.clear()
            self._worker = asyncio.create_task(self._loop(), name="vyom-curator")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._worker.cancel()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if await self._should_run():
                    await self.run_once()
            except Exception:
                logger.exception("Curator pass failed; will retry next poll")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _should_run(self) -> bool:
        """Idle-triggered gate, same shape as Hermes curator.py's
        maybe_run_curator(): only run when (a) enough time has passed
        since the last run, AND (b) nothing has happened recently
        (no task created inside min_idle_minutes)."""
        last_run = await self.run_store.last_run_at()
        now = datetime.now(timezone.utc)
        if last_run is not None:
            hours_since = (now - last_run).total_seconds() / 3600
            if hours_since < self.interval_hours:
                return False

        recent_tasks = await self.task_store.list(limit=1)
        if recent_tasks:
            latest = recent_tasks[0]
            reference = latest.completed_at or latest.created_at
            idle_minutes = (now - reference).total_seconds() / 60
            if idle_minutes < self.min_idle_minutes:
                return False
        return True

    async def run_once(self) -> dict:
        """Runs one review pass and records it. Public so it can also be
        triggered manually (e.g. a 'run curator now' API/CLI action) for
        testing or an impatient user, not only via the idle loop."""
        summary: dict = {"knowledge_lint": None, "stale_automations": [], "dialectic_findings": []}

        if self.knowledge_service is not None:
            try:
                summary["knowledge_lint"] = await self.knowledge_service.lint()
            except Exception as error:
                summary["knowledge_lint_error"] = str(error)[:300]

        if self.automation_store is not None:
            try:
                automations = await self.automation_store.list()
                summary["stale_automations"] = [
                    {"id": a.id, "name": a.name, "status": a.status.value}
                    for a in automations if getattr(a.status, "value", a.status) == "paused"
                ][:10]
            except Exception as error:
                summary["automation_check_error"] = str(error)[:300]

        # DIALECTIC REASONING (Honcho-style). Distinct from knowledge_lint
        # above (which only audits EXISTING facts): this actively derives
        # NEW facts from the raw conversation transcript that were never
        # explicitly told to memory - preferences, recurring topics - the
        # "understanding that goes beyond what was explicitly stated".
        if self.dialectic_reasoner is not None:
            try:
                findings = await self.dialectic_reasoner.run()
                summary["dialectic_findings"] = [
                    {"subject": f.subject, "predicate": f.predicate, "value": f.value, "confidence": f.confidence}
                    for f in findings
                ]
            except Exception as error:
                summary["dialectic_reasoning_error"] = str(error)[:300]

        run_id = await self.run_store.record(status="completed", summary=summary)
        summary["run_id"] = run_id

        if self.event_bus is not None:
            try:
                contradicted = (summary.get("knowledge_lint") or {}).get("totals", {}).get("contradicted", 0)
                stale = len(summary.get("stale_automations", []))
                await self.event_bus.publish(BrainEvent(
                    task_id=run_id,
                    type=EventType.CURATOR_RUN_COMPLETED,
                    human_readable_message=f"Curator pass complete: {contradicted} contradicted fact(s), {stale} paused automation(s)",
                    structured_payload={"curator_run": summary},
                ))
            except Exception:
                logger.debug("Failed to emit curator event", exc_info=True)

        return summary
