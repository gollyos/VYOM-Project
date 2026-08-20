from __future__ import annotations

from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType

from .audit import DistributedAuditLog
from .budgets import GlobalBudgetManager
from .leases import LeaseError, LeaseManager
from .node_router import NodeRouter
from .schemas import DispatchOutcome, TaskRequirements


class DispatchError(Exception):
    pass


class TaskDispatcher:
    """Places a task on a node: router selects a capable, online,
    trusted node; the lease manager guarantees single ownership; the
    budget manager blocks runaway concurrent work; every dispatch is
    journaled to the distributed audit log and the event bus."""

    def __init__(
        self,
        router: NodeRouter,
        leases: LeaseManager,
        audit: DistributedAuditLog,
        budgets: GlobalBudgetManager | None = None,
        event_bus: EventBus | None = None,
        executor=None,
    ):
        self.router = router
        self.leases = leases
        self.audit = audit
        self.budgets = budgets
        self.event_bus = event_bus
        self.executor = executor  # async callable(node, task_id, requirements) -> dict

    async def _emit(self, event_type: EventType, task_id: str, message: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id=task_id,
            type=event_type,
            human_readable_message=message,
            structured_payload=payload,
        ))

    async def dispatch(
        self, task_id: str, requirements: TaskRequirements, *, lease_ttl_seconds: int | None = None,
    ) -> DispatchOutcome:
        if self.budgets is not None:
            allowed, violations = await self.budgets.check_allowed(concurrent_tasks=1)
            if not allowed:
                outcome = DispatchOutcome(task_id=task_id, node_id=None, status="deferred_budget", reasons=violations)
                await self.audit.record("dispatch_deferred_budget", task_id=task_id, result="deferred")
                return outcome

        decision = self.router.select(task_id, requirements)
        if not decision.placed or decision.node_id is None:
            outcome = DispatchOutcome(
                task_id=task_id, node_id=None, status="no_capable_node",
                reasons=decision.reasons,
            )
            await self.audit.record("dispatch_no_node", task_id=task_id, result="rejected", evidence="; ".join(decision.reasons))
            return outcome

        try:
            lease = await self.leases.acquire(task_id, decision.node_id, ttl_seconds=lease_ttl_seconds)
        except LeaseError as error:
            return DispatchOutcome(task_id=task_id, node_id=decision.node_id, status="already_leased", reasons=[str(error)])

        if self.budgets is not None:
            await self.budgets.record(concurrent_tasks=1)

        result: dict = {}
        executed = False
        if self.executor is not None:
            result = await self.executor(decision.node_id, task_id, requirements)
            executed = bool(result.get("ok", True))

        if executed:
            await self.leases.release(task_id, decision.node_id)
            if self.budgets is not None:
                await self.budgets.record(concurrent_tasks=-1)

        await self.audit.record(
            "task_dispatched",
            node_id=decision.node_id,
            task_id=task_id,
            result="executed" if executed else "assigned",
        )
        await self._emit(
            EventType.TASK_DISPATCHED,
            task_id,
            f"Task dispatched to node {decision.node_id}",
            {"node_id": decision.node_id, "reasons": decision.reasons, "executed": executed},
        )
        return DispatchOutcome(
            task_id=task_id,
            node_id=decision.node_id,
            status="executed" if executed else "assigned",
            dispatched=True,
            lease_id=lease.lease_id,
            reasons=decision.reasons,
        )
