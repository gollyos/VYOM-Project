from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now


class RemoteSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex}")
    node_id: str
    user: str = "owner"
    created_at: datetime = Field(default_factory=utc_now)
    last_active_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    active_task_id: str | None = None
    last_command: str | None = None
    context_ids: list[str] = Field(default_factory=list)


class SessionContext(BaseModel):
    """Session continuity across devices: current task, recent command,
    relevant context IDs — reconstructed from structured state, never
    by syncing raw model context."""

    active_task_id: str | None = None
    last_command: str | None = None
    context_ids: list[str] = Field(default_factory=list)


class RemoteSessionManager:
    """Device sessions for remote command origin. Sessions are bound
    to an authenticated node, expire, and can be invalidated wholesale
    when a node is revoked."""

    def __init__(self, database, ttl_seconds: int = 3600):
        self.database = database
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, RemoteSession] = {}

    async def open(self, node_id: str, user: str = "owner") -> RemoteSession:
        session = RemoteSession(
            node_id=node_id, user=user,
            expires_at=utc_now() + timedelta(seconds=self.ttl_seconds),
        )
        self._sessions[session.session_id] = session
        await self._persist(session)
        return session

    def get(self, session_id: str) -> RemoteSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if utc_now() > session.expires_at:
            self._sessions.pop(session_id, None)
            return None
        return session

    def touch(self, session: RemoteSession) -> None:
        session.last_active_at = utc_now()

    async def update_context(self, session_id: str, *, active_task_id=None, last_command=None, context_ids=None) -> RemoteSession | None:
        session = self.get(session_id)
        if session is None:
            return None
        if active_task_id is not None:
            session.active_task_id = active_task_id
        if last_command is not None:
            session.last_command = last_command
        if context_ids is not None:
            session.context_ids = context_ids
        self.touch(session)
        await self._persist(session)
        return session

    def context_for_node(self, node_id: str) -> SessionContext:
        for session in self._sessions.values():
            if session.node_id == node_id and utc_now() <= session.expires_at:
                return SessionContext(
                    active_task_id=session.active_task_id,
                    last_command=session.last_command,
                    context_ids=session.context_ids,
                )
        return SessionContext()

    async def invalidate_node(self, node_id: str) -> int:
        removed = [sid for sid, session in self._sessions.items() if session.node_id == node_id]
        for session_id in removed:
            self._sessions.pop(session_id, None)
        return len(removed)

    async def _persist(self, session: RemoteSession) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO remote_sessions (session_id, node_id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
            """,
            (
                session.session_id, session.node_id, session.model_dump_json(),
                session.created_at.isoformat(), session.last_active_at.isoformat(),
            ),
        )
        await self.database.require_connection().commit()
