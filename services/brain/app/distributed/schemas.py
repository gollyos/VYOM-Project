from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now


class TaskRequirements(BaseModel):
    """What a task needs from the node that executes it. The router
    only ever matches these against capabilities a node actually
    registered — it never pretends a capability exists."""

    required_capabilities: list[str] = Field(default_factory=list)
    requires_gpu: bool = False
    requires_browser: bool = False
    requires_local_files: bool = False  # not portable across nodes
    local_project: str | None = None
    privacy: str = "standard"  # standard | local_only | cloud_ok
    preferred_node: str | None = None
    fallback_nodes: list[str] = Field(default_factory=list)
    consequential: bool = False  # external side effects (email/booking/...)
    max_latency_ms: int | None = None


class PlacementDecision(BaseModel):
    task_id: str
    node_id: str | None
    placed: bool
    reasons: list[str] = Field(default_factory=list)


class DispatchOutcome(BaseModel):
    task_id: str
    node_id: str | None
    status: str
    dispatched: bool = False
    lease_id: str | None = None
    reasons: list[str] = Field(default_factory=list)


class HandoffDecision(BaseModel):
    task_id: str
    portable: bool
    decision: str  # handoff | wait_for_owner | reject
    target_node: str | None = None
    reasons: list[str] = Field(default_factory=list)


class RecoveryAction(str, Enum):
    RESUME = "resume"
    RETRY = "retry"
    PAUSE = "pause"
    NEEDS_REVIEW = "needs_review"
    WAIT = "wait_for_owner"


class RecoveryDecision(BaseModel):
    task_id: str
    action: RecoveryAction
    reasons: list[str] = Field(default_factory=list)
    consequential: bool = False


class TaskLease(BaseModel):
    task_id: str
    node_id: str
    lease_id: str = Field(default_factory=lambda: f"lease_{uuid4().hex}")
    acquired_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    heartbeat_at: datetime = Field(default_factory=utc_now)


class NodeSummary(BaseModel):
    name: str
    node_id: str
    device_type: str
    online: str
    roles: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    runtime_health: str = "unknown"
