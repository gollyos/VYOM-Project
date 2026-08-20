from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ManifestEntry(BaseModel):
    deliverable: str
    file: str
    version: str
    description: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    verified: bool = False


class DeliveryManifest(BaseModel):
    """Useful for multi-file client work: one traceable row per
    deliverable, file, and version."""

    id: str = Field(default_factory=lambda: f"manifest_{uuid4().hex}")
    entries: list[ManifestEntry] = Field(default_factory=list)

    def add(self, entry: ManifestEntry) -> None:
        self.entries.append(entry)

    @property
    def all_verified(self) -> bool:
        return bool(self.entries) and all(entry.verified for entry in self.entries)
