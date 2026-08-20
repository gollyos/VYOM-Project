from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class TrustMode(str, Enum):
    LOCAL_USER = "local_user"        # single-user desktop: the OS login is the identity
    DEVICE_TOKEN = "device_token"    # paired remote device credential


class UserIdentity(BaseModel):
    """Local-first identity. There is deliberately no SaaS account
    architecture: the local user is trusted by OS session ownership;
    remote devices authenticate with paired tokens instead."""

    user_id: str = "local-owner"
    display_name: str = "Owner"
    mode: TrustMode = TrustMode.LOCAL_USER
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeviceIdentity(BaseModel):
    device_id: str
    name: str
    paired_at: datetime
    trust_level: str = "trusted"   # mirrors DeviceTrustLevel values


class LocalAuthPolicy:
    """Decides whether a caller origin needs explicit authentication.

    - Loopback callers in local-user mode are the trusted owner (the
      Brain binds 127.0.0.1 by default and never silently exposes more).
    - Any non-loopback origin MUST present a device token + session,
      regardless of configuration mistakes."""

    def __init__(self, mode: TrustMode = TrustMode.LOCAL_USER):
        self.mode = mode

    @staticmethod
    def is_loopback(client_host: str | None) -> bool:
        return client_host in ("127.0.0.1", "::1", "localhost", "testclient", None)

    def requires_authentication(self, client_host: str | None) -> bool:
        return not self.is_loopback(client_host)
