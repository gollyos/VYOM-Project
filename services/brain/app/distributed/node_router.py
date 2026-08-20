from __future__ import annotations

from dataclasses import dataclass, field

from app.devices.registry import DeviceRegistry
from app.devices.schemas import (
    DeviceCapability,
    DeviceNode,
    DeviceOnlineStatus,
    DeviceTrustLevel,
    NodeRole,
)

from .schemas import PlacementDecision, TaskRequirements


@dataclass
class RouterConfig:
    local_node_id: str = "brain-local"
    allow_local_fallback: bool = True
    privacy_local_only_device_types: tuple = ("desktop_pc", "laptop")


class NodeRouter:
    """Deterministic workload placement. No model call is involved:
    a node is eligible when it is capable, online, and trusted; the
    best candidate is preferred_node > fallback order > role/cost
    heuristics. Privacy flags keep local-only work off cloud nodes."""

    def __init__(self, registry: DeviceRegistry, config: RouterConfig | None = None):
        self.registry = registry
        self.config = config or RouterConfig()

    def _eligible(self, node: DeviceNode, requirements: TaskRequirements) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if node.trust_level != DeviceTrustLevel.TRUSTED:
            return False, [f"{node.name}: trust={node.trust_level.value}"]
        if node.online != DeviceOnlineStatus.ONLINE:
            return False, [f"{node.name}: {node.online.value}"]
        capabilities = set(node.capabilities)
        missing = [
            capability
            for capability in requirements.required_capabilities
            if capability not in capabilities
        ]
        if missing:
            return False, [f"{node.name}: missing capabilities {missing}"]
        if requirements.requires_gpu and DeviceCapability.GPU not in capabilities:
            return False, [f"{node.name}: no GPU"]
        if requirements.requires_browser and DeviceCapability.BROWSER not in capabilities:
            return False, [f"{node.name}: no browser"]
        if requirements.privacy == "local_only" and node.device_type.value == "cloud_worker":
            return False, [f"{node.name}: local-only work stays off cloud nodes"]
        if requirements.privacy == "local_only" and NodeRole.WORKER_NODE in node.roles and node.device_type.value == "home_server":
            pass  # home server is local hardware; acceptable for local_only
        # Power awareness: avoid heavy work on a low-battery portable node.
        if node.presence.on_battery and (node.presence.battery_percent or 100) < 20:
            if requirements.required_capabilities or requirements.requires_gpu:
                return False, [f"{node.name}: low battery ({node.presence.battery_percent}%)"]
        return True, reasons

    def select(self, task_id: str, requirements: TaskRequirements, *, exclude: set[str] | None = None) -> PlacementDecision:
        exclude = exclude or set()
        candidates: list[tuple[int, DeviceNode]] = []
        rejections: list[str] = []
        for node in self.registry.list():
            if node.node_id in exclude:
                rejections.append(f"{node.name}: excluded from this placement")
                continue
            eligible, reasons = self._eligible(node, requirements)
            if not eligible:
                rejections.extend(reasons)
                continue
            candidates.append((self._score(node, requirements), node))

        if requirements.preferred_node:
            for _, node in candidates:
                if node.node_id == requirements.preferred_node:
                    return PlacementDecision(task_id=task_id, node_id=node.node_id, placed=True, reasons=["preferred node matched"])
            rejections.append(f"preferred node {requirements.preferred_node} not eligible")

        for fallback_id in requirements.fallback_nodes:
            for _, node in candidates:
                if node.node_id == fallback_id:
                    return PlacementDecision(task_id=task_id, node_id=node.node_id, placed=True, reasons=["fallback node matched"])

        if candidates:
            candidates.sort(key=lambda pair: pair[0], reverse=True)
            node = candidates[0][1]
            return PlacementDecision(task_id=task_id, node_id=node.node_id, placed=True, reasons=["best score among eligible nodes"])
        return PlacementDecision(task_id=task_id, node_id=None, placed=False, reasons=rejections or ["no eligible nodes"])

    @staticmethod
    def _score(node: DeviceNode, requirements: TaskRequirements) -> int:
        score = 0
        if NodeRole.WORKER_NODE in node.roles or node.device_type.value == "home_server":
            score += 3  # prefer always-on hardware for background work
        if node.presence.busy:
            score -= 2
        if node.presence.on_battery:
            score -= 1
        if node.runtime_health == "degraded":
            score -= 2
        if requirements.requires_local_files and node.device_type.value in ("desktop_pc", "laptop"):
            score += 2
        return score
