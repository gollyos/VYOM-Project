from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, Field

from app.devices.schemas import utc_now
from app.distributed.audit import DistributedAuditLog
from app.runtime.event_bus import EventBus
from app.schemas.approvals import PermissionLevel
from app.schemas.events import BrainEvent, EventType
from app.schemas.tasks import TaskStatus


class RemoteApprovalView(BaseModel):
    """The full context a remote approval must show: requested action,
    reason, impact, agent, evidence, risk. Never a one-tap blind
    approve for L3 without strong device verification."""

    task_id: str
    requested_action: str
    reason: str = ""
    impact: str = ""
    agent: str = ""
    evidence: list[str] = Field(default_factory=list)
    risk: str = "medium"
    permission_level: str = "L2"
    requires_strong_verification: bool = False


class ApprovalExpiredError(Exception):
    pass


class StrongVerificationRequired(Exception):
    pass


class RemoteApprovalService:
    """Remote approve/reject/modify/pause/cancel with expiry. An
    expired approval cannot be executed without re-evaluation — the
    Brain re-runs the permission check and re-emits a fresh approval.
    L3 additionally requires strong verification (device biometric /
    OS secure confirmation attestation) — VYOM never stores its own
    PINs."""

    def __init__(
        self,
        task_store,
        runtime,
        audit: DistributedAuditLog,
        event_bus: EventBus | None = None,
        *,
        approval_ttl_seconds: int = 1800,
    ):
        self.task_store = task_store
        self.runtime = runtime
        self.audit = audit
        self.event_bus = event_bus
        self.approval_ttl_seconds = approval_ttl_seconds

    async def pending(self) -> list[RemoteApprovalView]:
        views: list[RemoteApprovalView] = []
        tasks = await self.task_store.list_by_status({TaskStatus.NEEDS_APPROVAL})
        for task in tasks:
            approval = task.metadata.get("approval") if task.metadata else None
            if not approval:
                continue
            metadata = task.metadata or {}
            level = str(approval.get("permission_level", metadata.get("permission_level", "L2")))
            views.append(RemoteApprovalView(
                task_id=task.id,
                requested_action=str(approval.get("reason", task.user_request)),
                reason=str(approval.get("reason", "")),
                impact=str(approval.get("impact", "")) or ("external action" if level.upper() == "L3" else "VYOM-side action"),
                agent=str(approval.get("agent", "VYOM")),
                evidence=list(approval.get("evidence", [])),
                risk=str(approval.get("risk", "high" if level.upper() == "L3" else "medium")),
                permission_level=level,
                requires_strong_verification=level.upper() == "L3",
            ))
        return views

    def _approval_age(self, task) -> float:
        approval = (task.metadata or {}).get("approval") or {}
        created = approval.get("created_at")
        if created is None:
            return 0.0
        try:
            from datetime import datetime

            created_dt = datetime.fromisoformat(str(created))
        except ValueError:
            return 0.0
        return (utc_now() - created_dt).total_seconds()

    async def _check_expiry(self, task) -> None:
        if self._approval_age(task) > self.approval_ttl_seconds:
            raise ApprovalExpiredError(
                f"Approval for task {task.id} expired after {self.approval_ttl_seconds}s; "
                "re-evaluation is required before it can execute"
            )

    async def decide(
        self,
        task_id: str,
        decision: str,
        *,
        node_id: str,
        strong_verification: bool = False,
        modification: str | None = None,
    ) -> dict:
        """decision: approve | reject | modify | pause | cancel."""
        task = await self.task_store.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status != TaskStatus.NEEDS_APPROVAL:
            raise ValueError(f"Task {task_id} is not awaiting approval (status {task.status.value})")

        await self._check_expiry(task)
        approval = (task.metadata or {}).get("approval") or {}
        level = str(approval.get("permission_level", "L2")).upper()
        if decision == "approve" and level == "L3" and not strong_verification:
            raise StrongVerificationRequired(
                "L3 approval requires device biometric / OS secure confirmation attestation"
            )

        if decision == "approve":
            resolved = await self.runtime.decide_approval(task_id, True)
            result = {"task_id": task_id, "decision": "approved", "status": resolved.status.value}
        elif decision == "reject":
            resolved = await self.runtime.decide_approval(task_id, False)
            result = {"task_id": task_id, "decision": "rejected", "status": resolved.status.value}
        elif decision == "pause":
            resolved = await self.runtime.pause(task_id)
            result = {"task_id": task_id, "decision": "paused", "status": resolved.status.value}
        elif decision == "cancel":
            resolved = await self.runtime.cancel(task_id)
            result = {"task_id": task_id, "decision": "cancelled", "status": resolved.status.value}
        elif decision == "modify":
            if modification is None:
                raise ValueError("modify requires a modification string")
            resolved = await self.runtime.pause(task_id)
            result = {
                "task_id": task_id, "decision": "modified", "status": resolved.status.value,
                "modification": modification,
            }
        else:
            raise ValueError(f"Unknown decision {decision!r}")

        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id=task_id, type=EventType.MOBILE_APPROVAL_RECEIVED,
                human_readable_message=f"Remote approval decision '{decision}' from node {node_id}",
                structured_payload={"decision": decision, "node_id": node_id, "task_id": task_id},
            ))
        await self.audit.record(
            f"remote_approval_{decision}", node_id=node_id, task_id=task_id, result=decision,
        )
        return result
