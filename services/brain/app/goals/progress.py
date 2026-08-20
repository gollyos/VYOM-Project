from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import Goal, Milestone, MilestoneStatus


class GoalEvidence(BaseModel):
    """Real signals supplied by the caller (CRM counts, habit event
    consistency, task completion) — never invented here. Each is optional;
    absence just means that signal isn't available yet (rule 6)."""

    crm_progress: float | None = None          # 0-1, e.g. clients_won / target_clients
    habit_consistency: float | None = None      # 0-1, from real habit events
    task_completion_ratio: float | None = None  # 0-1


class GoalProgressResult(BaseModel):
    progress: float | None = None
    basis: str
    sample_evidence: list[str] = Field(default_factory=list)


class GoalProgressEvaluator:
    """Never lets a bare percentage appear without a defined basis
    (rule 6). Milestone completion is always available as real local
    evidence once milestones exist; additional signals (CRM/habit/task)
    refine the number only when the caller actually supplies them."""

    def evaluate(self, goal: Goal, milestones: list[Milestone], evidence: GoalEvidence | None = None) -> GoalProgressResult:
        signals: list[float] = []
        basis_parts: list[str] = []
        sample_evidence: list[str] = []

        if milestones:
            done = sum(1 for m in milestones if m.status == MilestoneStatus.DONE)
            milestone_progress = done / len(milestones)
            signals.append(milestone_progress)
            basis_parts.append(f"{done}/{len(milestones)} milestones complete")
            sample_evidence.extend(f"milestone:{m.id}:{m.status.value}" for m in milestones if m.status == MilestoneStatus.DONE)

        if evidence is not None:
            if evidence.crm_progress is not None:
                signals.append(evidence.crm_progress)
                basis_parts.append(f"CRM signal {evidence.crm_progress:.0%}")
                sample_evidence.append(f"crm_progress:{evidence.crm_progress}")
            if evidence.habit_consistency is not None:
                signals.append(evidence.habit_consistency)
                basis_parts.append(f"habit consistency {evidence.habit_consistency:.0%}")
                sample_evidence.append(f"habit_consistency:{evidence.habit_consistency}")
            if evidence.task_completion_ratio is not None:
                signals.append(evidence.task_completion_ratio)
                basis_parts.append(f"task completion {evidence.task_completion_ratio:.0%}")
                sample_evidence.append(f"task_completion:{evidence.task_completion_ratio}")

        if not signals:
            return GoalProgressResult(progress=None, basis="No milestones or verified evidence are available yet", sample_evidence=[])

        progress = round(sum(signals) / len(signals), 4)
        return GoalProgressResult(progress=progress, basis="; ".join(basis_parts), sample_evidence=sample_evidence)
