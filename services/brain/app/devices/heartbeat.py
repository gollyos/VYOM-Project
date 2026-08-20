from __future__ import annotations

from datetime import datetime, timezone

from .schemas import DeviceOnlineStatus


class HeartbeatMonitor:
    """Tracks online/offline/degraded per node from received heartbeats.
    Never pretends an offline device completed an action -- a node with
    no recent heartbeat is reported OFFLINE, not silently assumed OK."""

    def __init__(self, offline_after_seconds: int = 60):
        self.offline_after_seconds = offline_after_seconds
        self._last_seen: dict[str, datetime] = {}
        self._latency_ms: dict[str, float] = {}

    def record(self, node_id: str, *, latency_ms: float = 0.0) -> None:
        self._last_seen[node_id] = datetime.now(timezone.utc)
        self._latency_ms[node_id] = latency_ms

    def status_for(self, node_id: str) -> DeviceOnlineStatus:
        last_seen = self._last_seen.get(node_id)
        if last_seen is None:
            return DeviceOnlineStatus.OFFLINE
        age = (datetime.now(timezone.utc) - last_seen).total_seconds()
        if age > self.offline_after_seconds:
            return DeviceOnlineStatus.OFFLINE
        if age > self.offline_after_seconds / 2:
            return DeviceOnlineStatus.DEGRADED
        return DeviceOnlineStatus.ONLINE

    def last_seen(self, node_id: str) -> datetime | None:
        return self._last_seen.get(node_id)

    def latency_ms(self, node_id: str) -> float | None:
        return self._latency_ms.get(node_id)
