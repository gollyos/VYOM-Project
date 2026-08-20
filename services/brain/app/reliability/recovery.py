from __future__ import annotations

from app.devices.schemas import utc_now
from app.distributed.audit import DistributedAuditLog
from app.distributed.leases import LeaseManager
from app.distributed.ownership import TaskOwnershipRegistry
from app.distributed.schemas import RecoveryAction, RecoveryDecision
from app.schemas.tasks import TaskStatus

from .checkpoints import CheckpointStore

ACTIVE_STATUSES = {
    TaskStatus.QUEUED, TaskStatus.UNDERSTANDING, TaskStatus.PLANNING,
    TaskStatus.WAITING, TaskStatus.EXECUTING, TaskStatus.VERIFYING,
}


class RecoveryService:
    """After a Brain restart: load persisted tasks, detect previously
    running tasks, inspect checkpoint/evidence, and decide resume /
    retry / pause / needs_review. Consequential tasks whose external
    action may already have happened go to needs_review — a restart
    never blindly repeats a consequential external action."""

    def __init__(
        self,
        task_store,
        checkpoints: CheckpointStore,
        ownership: TaskOwnershipRegistry,
        audit: DistributedAuditLog,
        leases: LeaseManager,
    ):
        self.task_store = task_store
        self.checkpoints = checkpoints
        self.ownership = ownership
        self.audit = audit
        self.leases = leases

    async def recover(self, now=None) -> list[RecoveryDecision]:
        now = now or utc_now()
        decisions: list[RecoveryDecision] = []
        tasks = await self.task_store.list_by_status(ACTIVE_STATUSES)
        for task in tasks:
            checkpoint = await self.checkpoints.get(task.id)
            decision = await self._decide(task, checkpoint)
            decisions.append(decision)
            await self.audit.record(
                f"recovery_{decision.action.value}", task_id=task.id, result=decision.action.value,
                evidence="; ".join(decision.reasons) or None,
            )
        return decisions

    async def _decide(self, task, checkpoint) -> RecoveryDecision:
        task_id = task.id
        consequential = task.permission_level is not None and task.permission_level.value.upper() in ("L2", "L3")

        executed_actions = list((checkpoint.completed_tool_calls if checkpoint else []))
        has_external_evidence = bool(checkpoint and checkpoint.evidence_references)

        if consequential and has_external_evidence:
            return RecoveryDecision(
                task_id=task_id, action=RecoveryAction.NEEDS_REVIEW, consequential=True,
                reasons=[
                    "consequential task has evidence of external actions before the restart",
                    "cannot safely determine whether the external action completed",
                ],
            )
        if consequential and executed_actions:
            return RecoveryDecision(
                task_id=task_id, action=RecoveryAction.NEEDS_REVIEW, consequential=True,
                reasons=["consequential task executed tool calls before the restart; reviewing before any retry"],
            )
        if checkpoint is not None:
            return RecoveryDecision(
                task_id=task_id, action=RecoveryAction.RESUME, consequential=consequential,
                reasons=["checkpoint exists; task can resume from persisted progress"],
            )
        lease = await self.leases.get(task_id)
        if lease is not None:
            return RecoveryDecision(
                task_id=task_id, action=RecoveryAction.RETRY, consequential=consequential,
                reasons=[f"lease held by {lease.node_id}; no checkpoint, safe deterministic retry"],
            )
        return RecoveryDecision(
            task_id=task_id, action=RecoveryAction.PAUSE, consequential=consequential,
            reasons=["no checkpoint and no lease; pausing for explicit resume"],
        )
