from __future__ import annotations

from .authentication import DevicePairingService
from .heartbeat import HeartbeatMonitor
from .schemas import DeviceNode, DeviceTrustLevel


class DeviceRegistry:
    """Foundation local registry of paired device nodes. See
    docs/DEVICE_NODE_PROTOCOL.md. Phase 12 adds an optional durable
    SQLite store so nodes/trust/revocations survive restarts; without
    one the registry keeps its original in-memory behavior."""

    def __init__(self, heartbeat: HeartbeatMonitor | None = None, store=None):
        self._nodes: dict[str, DeviceNode] = {}
        self.heartbeat = heartbeat or HeartbeatMonitor()
        self.store = store

    async def hydrate(self) -> list[DeviceNode]:
        if self.store is None:
            return []
        for node in await self.store.load_all():
            self._nodes[node.node_id] = node
        return self.list()

    def register(self, node: DeviceNode) -> DeviceNode:
        self._nodes[node.node_id] = node
        return node

    async def register_and_save(self, node: DeviceNode) -> DeviceNode:
        self.register(node)
        if self.store is not None:
            await self.store.save(node)
        return node

    def _refresh(self, node: DeviceNode) -> DeviceNode:
        node.online = self.heartbeat.status_for(node.node_id)
        node.last_seen = self.heartbeat.last_seen(node.node_id)
        return node

    def get(self, node_id: str) -> DeviceNode | None:
        node = self._nodes.get(node_id)
        return self._refresh(node) if node else None

    def list(self) -> list[DeviceNode]:
        return [self._refresh(node) for node in self._nodes.values()]

    def revoke(self, node_id: str, pairing: DevicePairingService) -> None:
        node = self._nodes.get(node_id)
        if node:
            node.trust_level = DeviceTrustLevel.REVOKED
        pairing.revoke(node_id)

    async def revoke_and_save(self, node_id: str, pairing: DevicePairingService) -> None:
        self.revoke(node_id, pairing)
        if self.store is not None:
            node = self._nodes.get(node_id)
            if node is not None:
                await self.store.save(node)
            if pairing.token_store is not None:
                await pairing.token_store.delete(node_id)
