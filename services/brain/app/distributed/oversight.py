from __future__ import annotations

from datetime import datetime

from app.schemas.tasks import TaskStatus

from .audit import DistributedAuditLog


class ActivitySummaryBuilder:
    """Builds the cross-device "What did VYOM do while I was away?"
    answer strictly from real persisted records: completed tasks,
    automation runs, audit entries, and pending approvals. It never
    invents activity for an empty period."""

    def __init__(self, task_store=None, automation_store=None, audit: DistributedAuditLog | None = None):
        self.task_store = task_store
        self.automation_store = automation_store
        self.audit = audit

    async def build(self, since: datetime) -> dict:
        summary: dict = {
            "since": since.isoformat(),
            "tasks_completed": [],
            "tasks_failed": [],
            "approvals_waiting": [],
            "automation_runs": [],
            "node_actions": [],
            "verified_evidence": [],
        }
        if self.task_store is not None:
            for task in await self.task_store.list(limit=500):
                completed = task.completed_at
                if completed is None or completed < since:
                    continue
                entry = {"task_id": task.id, "request": task.user_request}
                if task.status == TaskStatus.COMPLETED:
                    summary["tasks_completed"].append(entry)
                elif task.status == TaskStatus.FAILED:
                    summary["tasks_failed"].append(entry)
                elif task.status == TaskStatus.NEEDS_APPROVAL:
                    summary["approvals_waiting"].append(entry)
                if task.verification is not None and getattr(task.verification, "passed", False):
                    summary["verified_evidence"].append({"task_id": task.id})
        if self.automation_store is not None and hasattr(self.automation_store, "recent_runs"):
            for run in await self.automation_store.recent_runs(since_iso=since.isoformat(), limit=50):
                summary["automation_runs"].append({
                    "automation_id": run.automation_id,
                    "status": run.status,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                })
        if self.audit is not None:
            summary["node_actions"] = await self.audit.recent(limit=50, since_iso=since.isoformat())
        summary["empty"] = not any(
            summary[key] for key in (
                "tasks_completed", "tasks_failed", "approvals_waiting", "automation_runs", "node_actions",
            )
        )
        return summary
