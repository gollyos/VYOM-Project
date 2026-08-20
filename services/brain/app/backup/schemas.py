from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now


class BackupKind(str, Enum):
    MANUAL = "manual"
    DAILY = "daily"
    WEEKLY = "weekly"


class BackupManifest(BaseModel):
    backup_id: str = Field(default_factory=lambda: f"backup_{uuid4().hex[:12]}")
    kind: BackupKind = BackupKind.MANUAL
    created_at: datetime = Field(default_factory=utc_now)
    app_version: str = "0.1.0"
    schema_version: str = "1"
    parts: dict[str, str] = Field(default_factory=dict)   # relative path -> sha256
    size_bytes: int = 0
    encrypted: bool = False
    notes: str = ""
