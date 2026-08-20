from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now


class SyncEntity(str, Enum):
    TASK = "tasks"
    TASK_EVENT = "task_events"
    APPROVAL = "approvals"
    AGENT = "agents"
    AUTOMATION = "automations"
    MEMORY_METADATA = "memory_metadata"
    GOAL = "goals"
    NOTIFICATION = "notifications"
    DEVICE_STATE = "device_states"


class SyncAction(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"
    STATE = "state"


class SyncRecord(BaseModel):
    seq: int | None = None
    entity: SyncEntity
    entity_id: str
    action: SyncAction = SyncAction.UPSERT
    payload: dict = Field(default_factory=dict)
    origin_node: str = "brain-local"
    occurred_at: datetime = Field(default_factory=utc_now)


class ConflictPolicy(str, Enum):
    COORDINATOR_WINS = "coordinator_wins"      # sensitive/shared operational state
    TERMINAL_STATE_WINS = "terminal_state_wins"  # tasks: completed/failed are final
    FIELD_MERGE = "field_merge"                # goals/automations: newest per field, flag conflicts
    MANUAL_REVIEW = "manual_review"            # never auto-resolve


ENTITY_POLICIES: dict[SyncEntity, ConflictPolicy] = {
    SyncEntity.TASK: ConflictPolicy.TERMINAL_STATE_WINS,
    SyncEntity.TASK_EVENT: ConflictPolicy.COORDINATOR_WINS,
    SyncEntity.APPROVAL: ConflictPolicy.COORDINATOR_WINS,
    SyncEntity.AGENT: ConflictPolicy.COORDINATOR_WINS,
    SyncEntity.AUTOMATION: ConflictPolicy.FIELD_MERGE,
    SyncEntity.MEMORY_METADATA: ConflictPolicy.COORDINATOR_WINS,
    SyncEntity.GOAL: ConflictPolicy.FIELD_MERGE,
    SyncEntity.NOTIFICATION: ConflictPolicy.COORDINATOR_WINS,
    SyncEntity.DEVICE_STATE: ConflictPolicy.COORDINATOR_WINS,
}

TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


class SyncConflict(BaseModel):
    id: str = Field(default_factory=lambda: f"conflict_{uuid4().hex}")
    entity: SyncEntity
    entity_id: str
    local: dict
    remote: dict
    resolution: str
    resolved_payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class FreshnessView(BaseModel):
    """A cached view is never presented as live: every synced snapshot
    carries its as-of timestamp and a stale flag computed against the
    entity's freshness window."""

    entity: SyncEntity
    payload: dict
    as_of: datetime
    stale: bool
    age_seconds: float
