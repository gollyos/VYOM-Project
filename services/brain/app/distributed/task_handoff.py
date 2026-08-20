from __future__ import annotations

from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType

from .audit import DistributedAuditLog
from .leases import LeaseManager
from .node_router import NodeRouter
from .schemas import HandoffDecision, TaskRequirements


class TaskHandoffService:
    """Safe task handoff between nodes. A task is portable only when
    it does not depend on node-local files, projects, or desktop-only
    capabilities. Non-portable tasks wait honestly for their owning
    node; portable tasks are checkpointed by the caller and re-placed
    by the router on another eligible node."""

    def __init__(
        self,
        router: NodeRouter,
        leases: LeaseManager,
        audit: DistributedAuditLog,
        event_bus: EventBus | None = None,
        dispatcher=None,
    ):
        self.router = router
        self.leases = leases
        self.audit = audit
        self.event_bus = event_bus
        self.dispatcher = dispatcher

    async def _emit(self, event_type: EventType, task_id: str, message: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id=task_id, type=event_type, human_readable_message=message, structured_payload=payload,
        ))

    def evaluate_portability(self, requirements: TaskRequirements) -> HandoffDecision:
        reasons: list[str] = []
        portable = True
        if requirements.requires_local_files or requirements.local_project:
            portable = False
            reasons.append("task depends on node-local files/project; not portable")
        desktop_only = {"app.open", "screen.capture", "file.read", "file.write", "task.coding", "task.terminal"}
        if set(requirements.required_capabilities) & desktop_only and requirements.requires_local_files:
            portable = False
        if requirements.requires_gpu:
            portable = False
            reasons.append("task requires node-local GPU; portability depends on target hardware")
        if portable:
            reasons.append("task capabilities are portable")
        return HandoffDecision(task_id="", portable=portable, decision="handoff" if portable else "wait_for_owner", reasons=reasons)

    async def handoff(
        self,
        task_id: str,
        from_node: str,
        requirements: TaskRequirements,
        *,
        checkpoint: dict | None = None,
    ) -> HandoffDecision:
        evaluation = self.evaluate_portability(requirements)
        evaluation.task_id = task_id
        if not evaluation.portable:
            await self.audit.record("task_handoff_rejected", node_id=from_node, task_id=task_id, result="waiting_for_owner")
            await self._emit(
                EventType.TASK_HANDOFF_STARTED, task_id,
                "Task is not portable; waiting for its owning node",
                {"portable": False, "reasons": evaluation.reasons},
            )
            evaluation.decision = "wait_for_owner"
            return evaluation

        await self._emit(
            EventType.TASK_HANDOFF_STARTED, task_id,
            "Portable task handoff started",
            {"from_node": from_node, "checkpoint_saved": checkpoint is not None},
        )
        await self.leases.release(task_id, from_node)

        target_requirements = requirements.model_copy(update={"preferred_node": None})
        placement = self.router.select(task_id, target_requirements, exclude={from_node})
        if not placement.placed or placement.node_id is None:
            evaluation.decision = "wait_for_owner"
            evaluation.reasons = evaluation.reasons + placement.reasons
            await self.audit.record("task_handoff_no_target", node_id=from_node, task_id=task_id, result="waiting_for_owner")
            return evaluation

        evaluation.decision = "handoff"
        evaluation.target_node = placement.node_id
        await self.audit.record(
            "task_handoff_completed", node_id=placement.node_id, task_id=task_id,
            result=f"handed off from {from_node}",
        )
        await self._emit(
            EventType.TASK_HANDOFF_COMPLETED, task_id,
            f"Task handed off to node {placement.node_id}",
            {"from_node": from_node, "to_node": placement.node_id},
        )
        return evaluation
