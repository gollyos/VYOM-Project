from __future__ import annotations

from app.devices.registry import DeviceRegistry
from app.devices.schemas import DeviceCapability, DeviceOnlineStatus
from app.sync.journal import SyncJournal
from app.sync.schemas import SyncEntity


class ReplicationManager:
    """Chooses what shared state replicates to which node. Large
    private files never replicate automatically; mobile receives
    metadata/preview payloads only. Poor-network nodes get transfers
    deferred rather than retried endlessly."""

    MOBILE_ENTITIES = {
        SyncEntity.TASK, SyncEntity.APPROVAL, SyncEntity.NOTIFICATION,
        SyncEntity.DEVICE_STATE, SyncEntity.AUTOMATION, SyncEntity.GOAL,
    }
    WORKER_ENTITIES = set(SyncEntity)

    def __init__(self, registry: DeviceRegistry, journal: SyncJournal):
        self.registry = registry
        self.journal = journal

    def entities_for(self, node) -> set[SyncEntity]:
        if node.device_type.value == "mobile":
            return self.MOBILE_ENTITIES
        return self.WORKER_ENTITIES

    async def snapshot_for(self, node_id: str, since_seq: int = 0) -> dict:
        node = self.registry.get(node_id)
        if node is None:
            return {"node_id": node_id, "error": "unknown node", "records": []}
        if node.online == DeviceOnlineStatus.OFFLINE:
            return {"node_id": node_id, "deferred": True, "reason": "node offline", "records": []}
        if node.presence.network_type == "cellular":
            return {"node_id": node_id, "deferred": True, "reason": "poor network; large transfer deferred", "records": []}
        allowed = self.entities_for(node)
        records = [record for record in await self.journal.since(since_seq) if record.entity in allowed]
        return {
            "node_id": node_id,
            "deferred": False,
            "entities": sorted(entity.value for entity in allowed),
            "records": [record.model_dump(mode="json") for record in records],
        }

    def should_stream_artifact(self, node) -> bool:
        """Artifacts stream on authenticated request only; mobile gets
        metadata/preview, never automatic bulk file sync."""
        return DeviceCapability.FILE_READ in node.capabilities or node.device_type.value != "mobile"
