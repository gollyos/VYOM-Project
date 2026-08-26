from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Habit, HabitEvent, HabitStatus


class HabitStore:
    def __init__(self, database: Database, memory=None) -> None:
        self.database = database
        #: Optional MemoryManager - mirrors every habit save into the
        #: shared cross-domain memory graph (see
        #: app/memory/cross_domain.py) so "how are my habits going"
        #: research and goal-linkage can find it. None is fully
        #: supported; mirroring is purely additive.
        self.memory = memory

    async def save(self, habit: Habit) -> Habit:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO habits(id, status, habit_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, habit_json=excluded.habit_json, updated_at=excluded.updated_at""",
            (habit.id, habit.status.value, habit.model_dump_json(), habit.created_at.isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        await connection.commit()
        if self.memory is not None:
            from app.memory.cross_domain import mirror
            from app.memory.namespaces import CognitiveNamespace

            await mirror(
                self.memory, namespace=CognitiveNamespace.PERSONAL, domain_store="habit", record_id=habit.id,
                title=f"Habit: {habit.name}",
                content=f"{habit.name} ({habit.desired_direction.value}, {habit.frequency}, category: {habit.category}, status: {habit.status.value})",
                entities=[habit.name], extra_tags=[f"status:{habit.status.value}", f"category:{habit.category}"],
                importance=0.5,
            )
        return habit

    async def get(self, habit_id: str) -> Habit | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT habit_json FROM habits WHERE id = ?", (habit_id,))).fetchone()
        return Habit.model_validate_json(row["habit_json"]) if row else None

    async def find_by_name(self, name: str) -> Habit | None:
        normalized = name.strip().lower()
        for habit in await self.list():
            if habit.name.strip().lower() == normalized:
                return habit
        return None

    async def list(self, status: HabitStatus | None = None) -> list[Habit]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute("SELECT habit_json FROM habits WHERE status = ? ORDER BY created_at DESC", (status.value,))).fetchall()
        else:
            rows = await (await connection.execute("SELECT habit_json FROM habits ORDER BY created_at DESC")).fetchall()
        return [Habit.model_validate_json(row["habit_json"]) for row in rows]


class HabitEventStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, event: HabitEvent) -> HabitEvent:
        connection = self.database.require_connection()
        await connection.execute(
            "INSERT INTO habit_events(id, habit_id, timestamp, event_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (event.id, event.habit_id, event.timestamp.isoformat(), event.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
        await connection.commit()
        return event

    async def list_for_habit(self, habit_id: str, *, since: datetime | None = None) -> list[HabitEvent]:
        connection = self.database.require_connection()
        if since:
            rows = await (await connection.execute(
                "SELECT event_json FROM habit_events WHERE habit_id = ? AND timestamp >= ? ORDER BY timestamp ASC", (habit_id, since.isoformat())
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT event_json FROM habit_events WHERE habit_id = ? ORDER BY timestamp ASC", (habit_id,))).fetchall()
        return [HabitEvent.model_validate_json(row["event_json"]) for row in rows]
