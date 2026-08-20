from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.persistence.database import Database


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FocusSessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class FocusSessionResult(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    ABANDONED = "abandoned"


class FocusSession(BaseModel):
    id: str = Field(default_factory=lambda: f"focus_{uuid4().hex}")
    goal: str
    task_ids: list[str] = Field(default_factory=list)
    planned_minutes: float = 25.0
    start: datetime = Field(default_factory=utc_now)
    end: datetime | None = None
    duration_minutes: float | None = None
    interruptions: int = 0
    status: FocusSessionStatus = FocusSessionStatus.ACTIVE
    result: FocusSessionResult | None = None


class FocusSessionStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, session: FocusSession) -> FocusSession:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO focus_sessions(id, status, session_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, session_json=excluded.session_json, updated_at=excluded.updated_at""",
            (session.id, session.status.value, session.model_dump_json(), session.start.isoformat(), utc_now().isoformat()),
        )
        await connection.commit()
        return session

    async def get(self, session_id: str) -> FocusSession | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT session_json FROM focus_sessions WHERE id = ?", (session_id,))).fetchone()
        return FocusSession.model_validate_json(row["session_json"]) if row else None

    async def active(self) -> FocusSession | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT session_json FROM focus_sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1")).fetchone()
        return FocusSession.model_validate_json(row["session_json"]) if row else None

    async def list(self, *, limit: int = 50) -> list[FocusSession]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT session_json FROM focus_sessions ORDER BY created_at DESC LIMIT ?", (limit,))).fetchall()
        return [FocusSession.model_validate_json(row["session_json"]) for row in rows]


class FocusSessionService:
    """`FocusSession` lifecycle (rule 20/21). While a session is active,
    `is_active()` lets the notification/proactive layers suppress
    low-priority interruptions without blocking urgent approvals or user
    controls (rule 21) — enforced by the caller, this service only tracks
    state honestly."""

    def __init__(self, store: FocusSessionStore):
        self.store = store

    async def start(self, goal: str, *, task_ids: list[str] | None = None, planned_minutes: float = 25.0) -> FocusSession:
        existing = await self.store.active()
        if existing is not None:
            raise ValueError(f"A focus session is already active: {existing.goal}")
        session = FocusSession(goal=goal, task_ids=task_ids or [], planned_minutes=planned_minutes)
        return await self.store.save(session)

    async def pause(self, session_id: str) -> FocusSession:
        session = await self._require(session_id)
        session.status = FocusSessionStatus.PAUSED
        return await self.store.save(session)

    async def resume(self, session_id: str) -> FocusSession:
        session = await self._require(session_id)
        session.status = FocusSessionStatus.ACTIVE
        return await self.store.save(session)

    async def record_interruption(self, session_id: str) -> FocusSession:
        session = await self._require(session_id)
        session.interruptions += 1
        return await self.store.save(session)

    async def complete(self, session_id: str, *, result: FocusSessionResult = FocusSessionResult.COMPLETED) -> FocusSession:
        session = await self._require(session_id)
        session.end = utc_now()
        session.duration_minutes = round((session.end - session.start).total_seconds() / 60, 2)
        session.status = FocusSessionStatus.COMPLETED
        session.result = result
        return await self.store.save(session)

    async def is_active(self) -> bool:
        return (await self.store.active()) is not None

    async def _require(self, session_id: str) -> FocusSession:
        session = await self.store.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session
