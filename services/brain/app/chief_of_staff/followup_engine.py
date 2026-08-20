from __future__ import annotations

from pydantic import BaseModel, Field

from app.personal.schemas import Commitment


class FollowUpItem(BaseModel):
    description: str
    category: str  # "email_awaiting_reply" | "client_decision_pending" | "agent_waiting_approval" | "task_blocked" | "meeting_action_overdue" | "booking_confirmation_pending"
    evidence: list[str] = Field(default_factory=list)
    urgency: str = "normal"


class FollowUpEngine:
    """Tracks unresolved items across the systems Chief of Staff already
    has visibility into (rule 30). This module only aggregates candidates
    from real records; whether/when to actually interrupt the user is
    decided by the Proactive Intelligence Engine's relevance gate."""

    def collect(
        self, *, overdue_commitments: list[Commitment] | None = None, drafts_awaiting_send: int = 0,
        agents_awaiting_approval: list[str] | None = None, blocked_tasks: list[str] | None = None,
    ) -> list[FollowUpItem]:
        items: list[FollowUpItem] = []

        for commitment in overdue_commitments or []:
            category = {
                "meeting_action_item": "meeting_action_overdue",
                "email_commitment": "email_awaiting_reply",
                "client_agreement": "client_decision_pending",
            }.get(commitment.source.value, "task_blocked")
            items.append(FollowUpItem(description=commitment.description, category=category, evidence=[f"commitment_id:{commitment.id}"], urgency="urgent"))

        if drafts_awaiting_send:
            items.append(FollowUpItem(description=f"{drafts_awaiting_send} draft(s) awaiting your review before sending", category="email_awaiting_reply", evidence=[f"draft_count:{drafts_awaiting_send}"], urgency="normal"))

        for label in agents_awaiting_approval or []:
            items.append(FollowUpItem(description=label, category="agent_waiting_approval", evidence=[f"agent_item:{label}"], urgency="important"))

        for label in blocked_tasks or []:
            items.append(FollowUpItem(description=label, category="task_blocked", evidence=[f"blocked_item:{label}"], urgency="normal"))

        return items
