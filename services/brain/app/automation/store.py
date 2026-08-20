from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Automation, AutomationRun, AutomationStatus


class AutomationStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, automation: Automation) -> None:
        automation.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO automations(id, status, next_run_at, automation_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, next_run_at=excluded.next_run_at,
               automation_json=excluded.automation_json, updated_at=excluded.updated_at""",
            (automation.id, automation.status.value, automation.next_run_at.isoformat() if automation.next_run_at else None,
             automation.model_dump_json(), automation.created_at.isoformat(), automation.updated_at.isoformat()),
        )
        await connection.commit()

    async def get(self, automation_id: str) -> Automation:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT automation_json FROM automations WHERE id = ?", (automation_id,))).fetchone()
        if row is None:
            raise KeyError(automation_id)
        return Automation.model_validate_json(row["automation_json"])

    async def list(self) -> list[Automation]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT automation_json FROM automations ORDER BY updated_at DESC")).fetchall()
        return [Automation.model_validate_json(row["automation_json"]) for row in rows]

    async def due(self, now: datetime, limit: int = 10) -> list[Automation]:
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            """SELECT automation_json FROM automations
               WHERE status = ? AND next_run_at IS NOT NULL AND next_run_at <= ?
               ORDER BY next_run_at ASC LIMIT ?""",
            (AutomationStatus.ACTIVE.value, now.isoformat(), limit),
        )).fetchall()
        return [Automation.model_validate_json(row["automation_json"]) for row in rows]

    async def conditional(self, limit: int = 100) -> list[Automation]:
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT automation_json FROM automations WHERE status = ? AND next_run_at IS NULL "
            "ORDER BY updated_at ASC LIMIT ?",
            (AutomationStatus.ACTIVE.value, min(max(limit, 1), 500)),
        )).fetchall()
        return [
            automation for automation in (Automation.model_validate_json(row["automation_json"]) for row in rows)
            if automation.type.value == "conditional"
        ]

    async def begin_run(self, run: AutomationRun) -> bool:
        connection = self.database.require_connection()
        try:
            await connection.execute(
                "INSERT INTO automation_runs(id, automation_id, idempotency_key, status, run_json, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run.id, run.automation_id, run.idempotency_key, run.status, run.model_dump_json(), run.started_at.isoformat()),
            )
            await connection.commit()
            return True
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                return False
            raise

    async def finish_run(self, run: AutomationRun) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            "UPDATE automation_runs SET status = ?, run_json = ?, completed_at = ? WHERE id = ?",
            (run.status, run.model_dump_json(), run.completed_at.isoformat() if run.completed_at else None, run.id),
        )
        await connection.commit()

    async def runs_today(self, automation_id: str, now: datetime) -> int:
        start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT COUNT(*) AS total FROM automation_runs WHERE automation_id = ? AND started_at >= ?",
            (automation_id, start.isoformat()),
        )).fetchone()
        return int(row["total"])

    async def recent_runs(self, since_iso: str, limit: int = 50) -> list[AutomationRun]:
        """Phase 12: recent completed runs across all automations, used
        by the cross-device activity summary and reliability metrics."""
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT run_json FROM automation_runs WHERE completed_at IS NOT NULL AND completed_at >= ? "
            "ORDER BY completed_at DESC LIMIT ?",
            (since_iso, limit),
        )).fetchall()
        return [AutomationRun.model_validate_json(row["run_json"]) for row in rows]
