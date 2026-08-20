from __future__ import annotations

from pydantic import BaseModel, Field

from app.goals.evaluator import GoalHealthReport
from app.personal.schemas import Commitment
from app.productivity.workload import WorkloadAssessment, WorkloadLevel


class RiskItem(BaseModel):
    description: str
    severity: str  # "normal" | "important" | "urgent" | "critical"
    evidence: list[str] = Field(default_factory=list)


class RiskDetector:
    """Surfaces risk only from real signals already computed elsewhere
    (workload, overdue commitments, neglected goals, pending approvals) —
    never a speculative "something might go wrong.\""""

    def detect(
        self, *, workload: WorkloadAssessment | None = None, overdue_commitments: list[Commitment] | None = None,
        neglected_goals: list[GoalHealthReport] | None = None, pending_approvals: int = 0,
    ) -> list[RiskItem]:
        risks: list[RiskItem] = []

        if workload is not None and workload.level == WorkloadLevel.OVERLOADED:
            risks.append(RiskItem(
                description=f"Workload is overloaded ({workload.committed_hours:.1f}h committed vs {workload.available_hours:.1f}h available): {', '.join(workload.reasons)}",
                severity="important", evidence=[f"committed_hours:{workload.committed_hours}", f"available_hours:{workload.available_hours}"],
            ))

        for commitment in overdue_commitments or []:
            risks.append(RiskItem(
                description=f"Overdue commitment: {commitment.description}" + (f" (to {commitment.recipient})" if commitment.recipient else ""),
                severity="urgent", evidence=[f"commitment_id:{commitment.id}"],
            ))

        for report in neglected_goals or []:
            if report.neglected:
                risks.append(RiskItem(description=f"Neglected goal: {'; '.join(report.reasons)}", severity="normal", evidence=[f"goal_id:{report.goal_id}"]))

        if pending_approvals >= 3:
            risks.append(RiskItem(description=f"{pending_approvals} tasks are waiting on your approval", severity="important", evidence=[f"pending_approvals:{pending_approvals}"]))

        return risks
