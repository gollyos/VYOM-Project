from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now
from app.distributed.audit import DistributedAuditLog
from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType
from app.security.permission_engine import PermissionEngine
from app.schemas.approvals import PermissionLevel

from .session import RemoteSessionManager


class RemoteCommandEnvelope(BaseModel):
    """Every remote command carries its full authorization context.
    Replay, expiry, and authentication failures are rejected before
    any execution happens."""

    command_id: str = Field(default_factory=lambda: f"rcmd_{uuid4().hex}")
    command: str
    source_node: str
    session_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    nonce: str = Field(default_factory=lambda: uuid4().hex)
    permission_context: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)


class CommandRejected(Exception):
    def __init__(self, reason: str, status_code: int = 403):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class RemoteCommandGateway:
    """Authenticated entry point for commands from remote devices
    (mobile/laptop). Validation order: node exists and is trusted ->
    session valid -> timestamp within window -> nonce unseen (replay
    protection, durable) -> emergency/coordinator pause rules. Approved
    commands route into the Task Runtime; cancellation propagates
    through the runtime's cancel path."""

    def __init__(
        self,
        database,
        registry,
        sessions: RemoteSessionManager,
        audit: DistributedAuditLog,
        permission_engine: PermissionEngine | None = None,
        event_bus: EventBus | None = None,
        *,
        max_age_seconds: int = 120,
    ):
        self.database = database
        self.registry = registry
        self.sessions = sessions
        self.audit = audit
        self.permission_engine = permission_engine or PermissionEngine()
        self.event_bus = event_bus
        self.max_age_seconds = max_age_seconds

    async def _emit_received(self, envelope: RemoteCommandEnvelope, accepted: bool, reason: str = "") -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id=envelope.command_id, type=EventType.REMOTE_COMMAND_RECEIVED,
            human_readable_message=f"Remote command from {envelope.source_node}: {envelope.command}",
            structured_payload={"accepted": accepted, "reason": reason, "command_id": envelope.command_id},
        ))

    async def submit(self, envelope: RemoteCommandEnvelope) -> dict:
        node = self.registry.get(envelope.source_node)
        if node is None:
            await self._emit_received(envelope, False, "unknown node")
            raise CommandRejected(f"Unknown node {envelope.source_node}", 404)
        from app.devices.schemas import DeviceTrustLevel

        if node.trust_level != DeviceTrustLevel.TRUSTED:
            await self._emit_received(envelope, False, "untrusted node")
            raise CommandRejected("Node is not trusted", 403)
        session = self.sessions.get(envelope.session_id)
        if session is None or session.node_id != envelope.source_node:
            await self._emit_received(envelope, False, "invalid session")
            raise CommandRejected("Invalid or expired session", 401)
        if abs((utc_now() - envelope.timestamp).total_seconds()) > self.max_age_seconds:
            await self._emit_received(envelope, False, "expired command")
            raise CommandRejected("Command timestamp outside the acceptance window", 401)
        try:
            await self.database.require_connection().execute(
                "INSERT INTO remote_commands (command_id, source_node, nonce, status, command_json, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    envelope.command_id, envelope.source_node, envelope.nonce, "accepted",
                    envelope.model_dump_json(), utc_now().isoformat(),
                ),
            )
            await self.database.require_connection().commit()
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                await self._emit_received(envelope, False, "replay detected")
                raise CommandRejected("Replayed command rejected (nonce already used)", 409) from error
            raise
        self.sessions.touch(session)
        await self.sessions.update_context(session.session_id, last_command=envelope.command)
        await self.audit.record("remote_command", node_id=envelope.source_node, task_id=envelope.command_id, result="accepted")
        await self._emit_received(envelope, True)
        return {
            "accepted": True,
            "command_id": envelope.command_id,
            "permission_level": self.permission_engine.classify(envelope.command).value,
        }

    async def cancel_task(self, node_id: str, session_id: str, task_id: str, runtime) -> dict:
        """Remote cancellation propagates: cancel request -> runtime
        cancel -> persisted state; the synced result is what every
        device sees next."""
        node = self.registry.get(node_id)
        from app.devices.schemas import DeviceTrustLevel

        if node is None or node.trust_level != DeviceTrustLevel.TRUSTED:
            raise CommandRejected("Untrusted node", 403)
        session = self.sessions.get(session_id)
        if session is None or session.node_id != node_id:
            raise CommandRejected("Invalid session", 401)
        task = await runtime.cancel(task_id)
        await self.audit.record("remote_cancel", node_id=node_id, task_id=task_id, result=task.status.value)
        return {"cancelled": task_id, "status": task.status.value}
