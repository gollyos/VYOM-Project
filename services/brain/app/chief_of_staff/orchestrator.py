from __future__ import annotations

from pydantic import BaseModel, Field

from app.goals.evaluator import GoalHealthReport
from app.personal.schemas import Commitment
from app.productivity.workload import WorkloadAssessment

from .commitment_tracker import CommitmentSummary, CommitmentSummaryBuilder
from .followup_engine import FollowUpEngine, FollowUpItem
from .opportunity_detector import OpportunityDetector, OpportunityItem
from .priority_engine import PriorityEngine, PriorityScore, PrioritySignal
from .recommendation_engine import RecommendationEngine, RecommendationResult
from .risk_detector import RiskDetector, RiskItem


class ChiefOfStaffContext(BaseModel):
    """The bounded bundle of already-fetched real data the orchestrator
    reasons over. This layer consumes existing VYOM systems; it never
    reaches around them (rule 26)."""

    candidate_actions: list[PrioritySignal] = Field(default_factory=list)
    workload: WorkloadAssessment | None = None
    open_commitments: list[Commitment] = Field(default_factory=list)
    overdue_commitments: list[Commitment] = Field(default_factory=list)
    neglected_goals: list[GoalHealthReport] = Field(default_factory=list)
    pending_approvals: int = 0
    delegatable_agent_work: list[str] = Field(default_factory=list)
    agents_awaiting_approval: list[str] = Field(default_factory=list)
    blocked_tasks: list[str] = Field(default_factory=list)
    drafts_awaiting_send: int = 0
    available_free_minutes: float = 0.0
    repeated_manual_actions: dict[str, int] = Field(default_factory=dict)


class ChiefOfStaffBriefing(BaseModel):
    needs_attention: list[RiskItem] = Field(default_factory=list)
    handled_automatically: list[str] = Field(default_factory=list)
    requires_user: list[FollowUpItem] = Field(default_factory=list)
    at_risk: list[RiskItem] = Field(default_factory=list)
    possibly_forgotten: list[str] = Field(default_factory=list)
    delegable: list[OpportunityItem] = Field(default_factory=list)
    ranked_priorities: list[PriorityScore] = Field(default_factory=list)
    recommendation: RecommendationResult
    commitments: CommitmentSummary


class ChiefOfStaffOrchestrator:
    """Answers: what needs attention, what can VYOM handle itself, what
    requires the user, what is at risk, what might be forgotten, what can
    be delegated, and what should happen next — all from data this layer
    consumes rather than bypasses (rule 26)."""

    def __init__(
        self,
        priority_engine: PriorityEngine | None = None,
        risk_detector: RiskDetector | None = None,
        opportunity_detector: OpportunityDetector | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        followup_engine: FollowUpEngine | None = None,
        commitment_summary_builder: CommitmentSummaryBuilder | None = None,
    ):
        self.priority_engine = priority_engine or PriorityEngine()
        self.risk_detector = risk_detector or RiskDetector()
        self.opportunity_detector = opportunity_detector or OpportunityDetector()
        self.recommendation_engine = recommendation_engine or RecommendationEngine()
        self.followup_engine = followup_engine or FollowUpEngine()
        self.commitment_summary_builder = commitment_summary_builder or CommitmentSummaryBuilder()

    def brief(self, context: ChiefOfStaffContext) -> ChiefOfStaffBriefing:
        ranked = self.priority_engine.rank(context.candidate_actions)
        risks = self.risk_detector.detect(
            workload=context.workload, overdue_commitments=context.overdue_commitments,
            neglected_goals=context.neglected_goals, pending_approvals=context.pending_approvals,
        )
        opportunities = self.opportunity_detector.detect(
            available_free_minutes=context.available_free_minutes, delegatable_agent_work=context.delegatable_agent_work,
            repeated_manual_actions=context.repeated_manual_actions,
        )
        followups = self.followup_engine.collect(
            overdue_commitments=context.overdue_commitments, drafts_awaiting_send=context.drafts_awaiting_send,
            agents_awaiting_approval=context.agents_awaiting_approval, blocked_tasks=context.blocked_tasks,
        )
        recommendation = self.recommendation_engine.recommend(ranked)
        commitments = self.commitment_summary_builder.build(context.open_commitments + context.overdue_commitments)

        possibly_forgotten = [f"Neglected goal: {'; '.join(report.reasons)}" for report in context.neglected_goals if report.neglected]

        return ChiefOfStaffBriefing(
            needs_attention=[r for r in risks if r.severity in {"important", "urgent", "critical"}],
            handled_automatically=context.delegatable_agent_work,
            requires_user=[f for f in followups if f.urgency in {"important", "urgent"}],
            at_risk=risks,
            possibly_forgotten=possibly_forgotten,
            delegable=opportunities,
            ranked_priorities=ranked,
            recommendation=recommendation,
            commitments=commitments,
        )
