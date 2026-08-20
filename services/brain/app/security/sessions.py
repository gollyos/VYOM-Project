from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import BaseModel, Field


class Scope:
    COMMANDS = "commands"
    APPROVALS = "approvals"
    STATUS = "status"
    ALL = {COMMANDS, APPROVALS, STATUS}


class SecuritySession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sec_{uuid4().hex}")
    device_id: str
    user_id: str = "local-owner"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scopes: list[str] = Field(default_factory=lambda: [Scope.COMMANDS, Scope.APPROVALS, Scope.STATUS])
    revoked: bool = False
    revoked_reason: str | None = None


class AccessToken(BaseModel):
    """Opaque bearer token; only its SHA-256 hash is persisted."""

    token_hash: str
    session_id: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionSecurityError(Exception):
    pass


class SessionSecurityManager:
    """Security-layer session lifecycle for remote access: create with
    a hashed access token, scope-limited, expiring, individually or
    wholesale revocable. Expired/revoked sessions fail immediately."""

    def __init__(self, ttl_seconds: int = 3600, max_sessions_per_device: int = 3):
        self.ttl_seconds = ttl_seconds
        self.max_sessions_per_device = max_sessions_per_device
        self._sessions: dict[str, SecuritySession] = {}
        self._tokens: dict[str, str] = {}  # session_id -> sha256(token)

    @staticmethod
    def _hash(token: str) -> str:
        import hashlib

        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def open_session(self, device_id: str, scopes: list[str] | None = None) -> tuple[SecuritySession, str]:
        device_sessions = [s for s in self._sessions.values() if s.device_id == device_id and not s.revoked]
        if len(device_sessions) >= self.max_sessions_per_device:
            raise SessionSecurityError(f"Device {device_id} already holds {self.max_sessions_per_device} sessions")
        session = SecuritySession(
            device_id=device_id,
            scopes=scopes or [Scope.STATUS],
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
        )
        self._sessions[session.session_id] = session
        token = token_urlsafe(32)
        self._tokens[session.session_id] = self._hash(token)
        return session, token

    def _live(self, session: SecuritySession) -> SecuritySession:
        if session.revoked:
            raise SessionSecurityError("Session revoked")
        if datetime.now(timezone.utc) >= session.expires_at:  # a 0-TTL session is expired immediately
            raise SessionSecurityError("Session expired")
        return session

    def validate(self, session_id: str, token: str, *, scope: str | None = None) -> SecuritySession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionSecurityError("Unknown session")
        self._live(session)
        import secrets as _secrets

        stored = self._tokens.get(session_id)
        if stored is None or not _secrets.compare_digest(stored, self._hash(token)):
            raise SessionSecurityError("Invalid access token")
        if scope is not None and scope not in session.scopes:
            raise SessionSecurityError(f"Session lacks required scope {scope!r}")
        session.last_activity = datetime.now(timezone.utc)
        return session

    def revoke_session(self, session_id: str, reason: str = "user request") -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.revoked = True
            session.revoked_reason = reason
            self._tokens.pop(session_id, None)

    def revoke_device(self, device_id: str) -> int:
        count = 0
        for session in self._sessions.values():
            if session.device_id == device_id and not session.revoked:
                self.revoke_session(session.session_id, reason=f"device {device_id} revoked")
                count += 1
        return count

    def revoke_all_remote(self, reason: str = "revoke all") -> int:
        count = 0
        for session in self._sessions.values():
            if not session.revoked:
                self.revoke_session(session.session_id, reason=reason)
                count += 1
        return count

    def prune_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [sid for sid, s in self._sessions.items() if now > s.expires_at]
        for session_id in expired:
            self._sessions.pop(session_id, None)
            self._tokens.pop(session_id, None)
        return len(expired)

    def active_sessions(self) -> list[SecuritySession]:
        now = datetime.now(timezone.utc)
        return sorted(
            (s for s in self._sessions.values() if not s.revoked and now <= s.expires_at),
            key=lambda s: s.last_activity,
            reverse=True,
        )
