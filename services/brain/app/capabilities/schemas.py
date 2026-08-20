from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.approvals import PermissionLevel


class CapabilitySource(str, Enum):
    BUILTIN_TOOL = "built_in_tool"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    AGENT = "agent"
    MODEL = "model"
    INTEGRATION = "integration"
    EXTERNAL = "external"


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RESTRICTED = "restricted"


class ExternalCapabilityStatus(str, Enum):
    """Phase 13.5 intake lifecycle. An external capability never becomes
    active directly from discovery."""

    DISCOVERED = "discovered"
    REVIEWING = "reviewing"
    SANDBOXED = "sandboxed"
    TESTING = "testing"
    APPROVED = "approved"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    REJECTED = "rejected"


class CapabilityBackend(BaseModel):
    """Agent-Reach-style routing principle implemented inside the
    existing registry: one capability, ordered backends with health,
    reliability, latency, and cost — deterministic selection with
    automatic fallback. No new router service; the registry owns it."""

    backend_id: str
    kind: str = "builtin"          # builtin | mcp | external | integration | browser
    preferred: bool = False
    health: str = "unknown"        # healthy | degraded | offline | unknown
    reliability: float = Field(default=0.5, ge=0, le=1)
    latency_ms: float | None = None
    cost: float = 0.0
    notes: str = ""


class ExternalCapabilityMeta(BaseModel):
    """External-capability metadata carried ON the existing
    CapabilityRecord — no second registry, no new database."""

    repository: str = ""
    version: str = ""              # pinned version/tag/commit
    license: str = ""
    trust_level: str = "untrusted" # untrusted | restricted | trusted
    intake_status: ExternalCapabilityStatus = ExternalCapabilityStatus.DISCOVERED
    network_access: bool = False
    filesystem_access: bool = False
    secret_access: bool = False
    benchmark: dict[str, Any] = Field(default_factory=dict)
    installed_at: datetime | None = None
    review_notes: list[str] = Field(default_factory=list)


class CapabilityRecord(BaseModel):
    capability_id: str
    name: str
    description: str
    source: CapabilitySource
    source_id: str
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    required_permissions: list[PermissionLevel] = Field(default_factory=lambda: [PermissionLevel.L0])
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reliability: float = Field(default=0.5, ge=0, le=1)
    last_verified: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    # Phase 13.5 (all optional — existing records unchanged)
    external: ExternalCapabilityMeta | None = None
    backends: list[CapabilityBackend] = Field(default_factory=list)


def verified_now() -> datetime:
    return datetime.now(timezone.utc)
