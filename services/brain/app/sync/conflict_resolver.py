from __future__ import annotations

from app.devices.schemas import utc_now

from .schemas import (
    ENTITY_POLICIES,
    TERMINAL_TASK_STATUSES,
    ConflictPolicy,
    SyncConflict,
    SyncEntity,
    SyncRecord,
)


class ConflictResolver:
    """Explicit, domain-specific conflict policies — never blind
    last-write-wins for sensitive records.

    - tasks: a terminal state (completed/failed/cancelled) always wins;
      otherwise the coordinator's record wins and the loser is flagged.
    - goals/automations: field-level merge — newer value per field, and
      any field changed on both sides since the common base is recorded
      as a conflict for the user.
    - everything else: coordinator wins, conflict still recorded."""

    def __init__(self, database=None):
        self.database = database

    async def _persist_conflict(self, conflict: SyncConflict) -> None:
        if self.database is None:
            return
        await self.database.require_connection().execute(
            """
            INSERT INTO sync_conflicts (id, entity, entity_id, resolution, conflict_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET conflict_json = excluded.conflict_json
            """,
            (
                conflict.id, conflict.entity.value, conflict.entity_id,
                conflict.resolution, conflict.model_dump_json(), conflict.created_at.isoformat(),
            ),
        )
        await self.database.require_connection().commit()

    def _resolve_terminal_state(self, conflict: SyncConflict) -> SyncConflict:
        local_status = str(conflict.local.get("status", "")).lower()
        remote_status = str(conflict.remote.get("status", "")).lower()
        if local_status in TERMINAL_TASK_STATUSES:
            conflict.resolution = f"terminal local state '{local_status}' wins"
            conflict.resolved_payload = conflict.local
        elif remote_status in TERMINAL_TASK_STATUSES:
            conflict.resolution = f"terminal remote state '{remote_status}' wins"
            conflict.resolved_payload = conflict.remote
        else:
            conflict.resolution = "coordinator record wins (no terminal state)"
            conflict.resolved_payload = conflict.local
        return conflict

    def _resolve_field_merge(self, conflict: SyncConflict) -> SyncConflict:
        base = conflict.local.get("_base", {}) or {}
        merged = dict(conflict.local)
        conflicted_fields: list[str] = []
        for field, remote_value in conflict.remote.items():
            if field.startswith("_"):
                continue
            local_changed = field in base and base.get(field) != merged.get(field)
            remote_changed = field in base and base.get(field) != remote_value
            if local_changed and remote_changed and merged.get(field) != remote_value:
                conflicted_fields.append(field)
                continue  # edited on both sides: keep coordinator value, flag for the user
            if local_changed:
                continue  # edited only here: keep the coordinator's newer value
            merged[field] = remote_value  # equal or edited only remotely: take remote
        merged.pop("_base", None)
        conflict.resolution = (
            f"field merge; conflicting fields kept from coordinator: {conflicted_fields}"
            if conflicted_fields else "field merge with no overlapping edits"
        )
        conflict.resolved_payload = merged
        conflict.created_at = utc_now()
        return conflict

    async def resolve(self, entity: SyncEntity, entity_id: str, local: dict, remote: dict) -> SyncConflict:
        conflict = SyncConflict(
            entity=entity, entity_id=entity_id, local=local, remote=remote, resolution="unresolved",
        )
        policy = ENTITY_POLICIES.get(entity, ConflictPolicy.COORDINATOR_WINS)
        if policy == ConflictPolicy.TERMINAL_STATE_WINS:
            conflict = self._resolve_terminal_state(conflict)
        elif policy == ConflictPolicy.FIELD_MERGE:
            conflict = self._resolve_field_merge(conflict)
        else:
            conflict.resolution = "coordinator wins"
            conflict.resolved_payload = local
        await self._persist_conflict(conflict)
        return conflict

    async def detect_and_resolve(self, incoming: SyncRecord, current: dict | None) -> tuple[dict, SyncConflict | None]:
        """Apply an incoming record against current local state. Returns
        the resolved payload and a conflict when the two diverged."""
        if current is None:
            return incoming.payload, None
        if current == incoming.payload:
            return current, None
        conflict = await self.resolve(incoming.entity, incoming.entity_id, current, incoming.payload)
        return conflict.resolved_payload, conflict
