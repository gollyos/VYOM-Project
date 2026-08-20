from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Routine, RoutineRun


class RoutineStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, routine: Routine) -> Routine:
        routine.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO routines(id, name, enabled, routine_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, enabled=excluded.enabled, routine_json=excluded.routine_json, updated_at=excluded.updated_at""",
            (routine.id, routine.name, int(routine.enabled), routine.model_dump_json(), routine.created_at.isoformat(), routine.updated_at.isoformat()),
        )
        await connection.commit()
        return routine

    async def get(self, routine_id: str) -> Routine | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT routine_json FROM routines WHERE id = ?", (routine_id,))).fetchone()
        return Routine.model_validate_json(row["routine_json"]) if row else None

    async def find_by_name(self, name: str) -> Routine | None:
        normalized = name.strip().lower()
        for routine in await self.list():
            if routine.name.strip().lower() == normalized:
                return routine
        return None

    async def list(self) -> list[Routine]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT routine_json FROM routines ORDER BY updated_at DESC")).fetchall()
        return [Routine.model_validate_json(row["routine_json"]) for row in rows]


class RoutineRunStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, run: RoutineRun) -> RoutineRun:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO routine_runs(id, routine_id, status, run_json, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, run_json=excluded.run_json, completed_at=excluded.completed_at""",
            (run.id, run.routine_id, run.status.value, run.model_dump_json(), run.started_at.isoformat(), run.completed_at.isoformat() if run.completed_at else None),
        )
        await connection.commit()
        return run

    async def list_for_routine(self, routine_id: str, *, limit: int = 20) -> list[RoutineRun]:
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT run_json FROM routine_runs WHERE routine_id = ? ORDER BY started_at DESC LIMIT ?", (routine_id, limit)
        )).fetchall()
        return [RoutineRun.model_validate_json(row["run_json"]) for row in rows]
