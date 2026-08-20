from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.artifacts.schemas import ArtifactRecord

from .manifest import DeliveryManifest, ManifestEntry


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeliveryApprovalStatus(str, Enum):
    DRAFT = "draft"
    QUALITY_CHECKED = "quality_checked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENT = "sent"
    FAILED = "failed"


class DeliveryPackage(BaseModel):
    id: str = Field(default_factory=lambda: f"delivery_{uuid4().hex}")
    client: str
    project: str
    deliverables: list[str] = Field(default_factory=list)
    manifest: DeliveryManifest = Field(default_factory=DeliveryManifest)
    version: str = "v1"
    quality_status: str = "unchecked"
    approval_status: DeliveryApprovalStatus = DeliveryApprovalStatus.DRAFT
    delivery_method: str | None = None
    evidence: list[str] = Field(default_factory=list)
    dedupe_key: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def compute_dedupe_key(self) -> str:
        raw = f"{self.client}|{self.project}|{self.version}|{','.join(sorted(self.deliverables))}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class PackageBuilder:
    """Selects the supplied artifact records (callers pass only
    approved/latest versions) and assembles a manifest-backed delivery
    package."""

    def build(self, *, client: str, project: str, artifacts: list[ArtifactRecord], version: str = "v1") -> DeliveryPackage:
        manifest = DeliveryManifest()
        deliverables: list[str] = []
        for artifact in artifacts:
            deliverables.append(artifact.spec.title)
            manifest.add(ManifestEntry(
                deliverable=artifact.spec.title,
                file=artifact.output_path or "",
                version=artifact.version,
                description=artifact.spec.purpose,
                verified=artifact.verified,
            ))
        package = DeliveryPackage(client=client, project=project, deliverables=deliverables, manifest=manifest, version=version)
        package.dedupe_key = package.compute_dedupe_key()
        return package
