from __future__ import annotations

from app.devices.registry import DeviceRegistry
from app.devices.schemas import DeviceNode, NodeVersionInfo, utc_now
from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType

from .audit import DistributedAuditLog
from .leases import LeaseManager
from .schemas import NodeSummary
from .task_handoff import TaskHandoffService

SUPPORTED_PROTOCOL_VERSION = 1


class VersionCompatibilityError(Exception):
    pass


class DistributedCoordinator:
    """Brain-side coordination façade for the multi-node runtime:
    node lifecycle with version gating, presence transitions, lease
    expiry handling with safe handoff, global pause/resume, and the
    cross-node status view. A device may hold several roles at once."""

    def __init__(
        self,
        registry: DeviceRegistry,
        leases: LeaseManager,
        audit: DistributedAuditLog,
        event_bus: EventBus | None = None,
        handoff: TaskHandoffService | None = None,
        automation_store=None,
        requirements_resolver=None,
    ):
        self.registry = registry
        self.leases = leases
        self.audit = audit
        self.event_bus = event_bus
        self.handoff = handoff
        self.automation_store = automation_store
        self.requirements_resolver = requirements_resolver  # callable(task_id) -> TaskRequirements
        self.paused = False
        self._paused_by_pause_everything: set[str] = set()

    async def _emit(self, event_type: EventType, message: str, payload: dict, task_id: str = "system") -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id=task_id, type=event_type, human_readable_message=message, structured_payload=payload,
        ))

    @staticmethod
    def check_version_compatibility(version_info: NodeVersionInfo) -> None:
        try:
            protocol_major = int(str(version_info.protocol_version).split(".")[0])
        except ValueError as error:
            raise VersionCompatibilityError(f"Unparseable protocol version {version_info.protocol_version!r}") from error
        if protocol_major != SUPPORTED_PROTOCOL_VERSION:
            raise VersionCompatibilityError(
                f"Node protocol {version_info.protocol_version} is incompatible with coordinator protocol {SUPPORTED_PROTOCOL_VERSION}"
            )

    async def register_node(self, node: DeviceNode) -> DeviceNode:
        self.check_version_compatibility(node.version_info)
        await self.registry.register_and_save(node)
        await self.audit.record("node_registered", node_id=node.node_id, result=node.name)
        await self._emit(EventType.NODE_REGISTERED, f"Node {node.name} registered", {"node_id": node.node_id, "roles": [r.value for r in node.roles]})
        return node

    async def record_heartbeat(
        self, node_id: str, *, presence: dict | None = None, runtime_health: str | None = None,
    ) -> DeviceNode | None:
        node = self.registry.get(node_id)
        if node is None:
            return None
        was_online = node.online.value == "online"
        self.registry.heartbeat.record(node_id)
        if presence:
            update = node.presence.model_dump()
            update.update(presence)
            node.presence = node.presence.model_validate(update)
        if runtime_health:
            node.runtime_health = runtime_health
        node.updated_at = utc_now()
        if self.registry.store is not None:
            await self.registry.store.save(node)
        refreshed = self.registry.get(node_id)
        if refreshed is not None and refreshed.online.value == "online" and not was_online:
            await self._emit(EventType.NODE_ONLINE, f"Node {node.name} is online", {"node_id": node_id})
        return refreshed

    async def mark_offline(self, node_id: str) -> None:
        node = self.registry.get(node_id)
        if node is None:
            return
        await self._emit(EventType.NODE_OFFLINE, f"Node {node.name} is offline", {"node_id": node_id})
        await self.audit.record("node_offline", node_id=node_id, result="offline")

    async def network_summary(self) -> list[NodeSummary]:
        return [
            NodeSummary(
                name=node.name,
                node_id=node.node_id,
                device_type=node.device_type.value,
                online=node.online.value,
                roles=[role.value for role in node.roles],
                capabilities=[capability.value for capability in node.capabilities],
                runtime_health=node.runtime_health,
            )
            for node in self.registry.list()
        ]

    async def handle_expired_leases(self, now=None) -> list[dict]:
        results: list[dict] = []
        for lease in await self.leases.expired(now=now):
            await self._emit(
                EventType.TASK_LEASE_EXPIRED,
                f"Lease on task {lease.task_id} expired (node {lease.node_id})",
                {"task_id": lease.task_id, "node_id": lease.node_id},
                task_id=lease.task_id,
            )
            await self.audit.record("task_lease_expired", node_id=lease.node_id, task_id=lease.task_id, result="expired")
            outcome = {"task_id": lease.task_id, "node_id": lease.node_id, "handoff": None}
            if self.handoff is not None and self.requirements_resolver is not None:
                requirements = self.requirements_resolver(lease.task_id)
                if requirements is not None:
                    decision = await self.handoff.handoff(lease.task_id, lease.node_id, requirements)
                    outcome["handoff"] = decision.model_dump()
            results.append(outcome)
        return results

    async def pause_everything(self, *, reason: str = "user requested") -> dict:
        """Pause non-critical autonomous work: block new dispatch and
        pause active automations. Active file/database operations are
        never aborted mid-write — pause is cooperative."""
        from app.automation.schemas import AutomationStatus

        self.paused = True
        paused_automations: list[str] = []
        if self.automation_store is not None:
            for automation in await self.automation_store.list():
                if automation.status.value == "active":
                    automation.status = AutomationStatus.PAUSED
                    await self.automation_store.save(automation)
                    paused_automations.append(automation.id)
        self._paused_by_pause_everything.update(paused_automations)
        await self.audit.record("pause_everything", result=f"paused {len(paused_automations)} automations", evidence=reason)
        return {"paused": True, "automations_paused": paused_automations}

    async def resume_all(self) -> dict:
        from app.automation.schemas import AutomationStatus

        self.paused = False
        resumed: list[str] = []
        if self.automation_store is not None:
            for automation in await self.automation_store.list():
                # Resume only what pause_everything paused or what had run
                # before — failure-paused automations stay paused until the
                # user explicitly re-enables them.
                if automation.status.value == "paused" and (
                    automation.id in self._paused_by_pause_everything or automation.last_run_at is not None
                ):
                    automation.status = AutomationStatus.ACTIVE
                    await self.automation_store.save(automation)
                    resumed.append(automation.id)
        self._paused_by_pause_everything.clear()
        await self.audit.record("resume_all", result=f"resumed {len(resumed)} automations")
        return {"paused": False, "automations_resumed": resumed}
