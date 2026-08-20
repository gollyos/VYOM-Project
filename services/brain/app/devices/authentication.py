from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from .schemas import DeviceCapability, DeviceNode, DeviceOnlineStatus, DeviceTrustLevel, DeviceType, PairingRequest


class PairingError(Exception):
    pass


class AuthenticationError(Exception):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DevicePairingService:
    """pair -> approve -> authenticate -> rotate -> revoke. No
    unauthenticated remote command is ever accepted; a device only
    becomes TRUSTED after explicit approval, and tokens are stored
    hashed, never in plaintext.

    Phase 12: pass a ``NodeTokenStore`` to make hashed credentials
    survive Brain restarts; call ``await load_tokens()`` during startup
    so authenticate() works against persisted pairings."""

    def __init__(
        self,
        code_ttl_seconds: int = 300,
        max_pending_requests: int = 5,
        token_store=None,
    ):
        self.code_ttl_seconds = code_ttl_seconds
        self.max_pending_requests = max_pending_requests
        self.token_store = token_store
        self._pending: dict[str, PairingRequest] = {}
        self._tokens: dict[str, str] = {}
        self._approved_claims: dict[str, tuple[str, DeviceNode, str, datetime]] = {}

    def _prune_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self._pending = {key: value for key, value in self._pending.items() if value.expires_at >= now}
        self._approved_claims = {
            key: value for key, value in self._approved_claims.items() if value[3] >= now
        }

    async def load_tokens(self) -> None:
        if self.token_store is None:
            return
        connection = self.token_store.database.require_connection()
        cursor = await connection.execute("SELECT node_id, token_hash FROM node_tokens")
        for row in await cursor.fetchall():
            self._tokens[row["node_id"]] = row["token_hash"]

    def start_pairing(
        self, name: str, device_type: DeviceType, platform: str, requested_capabilities: list[DeviceCapability],
    ) -> PairingRequest:
        self._prune_expired()
        if len(self._pending) >= self.max_pending_requests:
            raise PairingError("Too many pending pairing requests")
        code = secrets.token_hex(4)
        request = PairingRequest(
            name=name, device_type=device_type, platform=platform,
            requested_capabilities=requested_capabilities, code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.code_ttl_seconds),
        )
        self._pending[request.request_id] = request
        return request

    def approve(self, request_id: str, *, allowed_capabilities: list[DeviceCapability]) -> tuple[DeviceNode, str]:
        self._prune_expired()
        request = self._pending.pop(request_id, None)
        if request is None:
            raise PairingError("Unknown or already-resolved pairing request")
        if datetime.now(timezone.utc) > request.expires_at:
            raise PairingError("Pairing code expired")
        granted = [capability for capability in request.requested_capabilities if capability in allowed_capabilities]
        node = DeviceNode(
            name=request.name, device_type=request.device_type, platform=request.platform,
            capabilities=granted, trust_level=DeviceTrustLevel.TRUSTED, online=DeviceOnlineStatus.OFFLINE,
        )
        token = secrets.token_urlsafe(32)
        self._tokens[node.node_id] = _hash_token(token)
        self._approved_claims[request_id] = (request.code, node, token, request.expires_at)
        return node, token

    def pending(self) -> list[PairingRequest]:
        self._prune_expired()
        return list(self._pending.values())

    def claim(self, request_id: str, code: str) -> tuple[DeviceNode, str]:
        self._prune_expired()
        approved = self._approved_claims.get(request_id)
        if approved is None:
            if request_id in self._pending:
                raise PairingError("Pairing request is waiting for approval")
            raise PairingError("Unknown or expired pairing claim")
        expected_code, node, token, expires_at = approved
        if datetime.now(timezone.utc) > expires_at:
            self._approved_claims.pop(request_id, None)
            raise PairingError("Pairing claim expired")
        if not secrets.compare_digest(expected_code, code):
            raise PairingError("Pairing code does not match")
        self._approved_claims.pop(request_id, None)
        return node, token

    def reject(self, request_id: str) -> None:
        self._pending.pop(request_id, None)

    def authenticate(self, node_id: str, token: str) -> bool:
        stored = self._tokens.get(node_id)
        if stored is None:
            raise AuthenticationError("Unknown device; unauthenticated commands are never accepted")
        return secrets.compare_digest(stored, _hash_token(token))

    def rotate(self, node_id: str) -> str:
        if node_id not in self._tokens:
            raise AuthenticationError("Cannot rotate credentials for an unpaired device")
        token = secrets.token_urlsafe(32)
        self._tokens[node_id] = _hash_token(token)
        return token

    def revoke(self, node_id: str) -> None:
        self._tokens.pop(node_id, None)
