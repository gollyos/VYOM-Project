from __future__ import annotations

from pydantic import BaseModel, Field

from app.personal.schemas import Commitment


class CommitmentSummary(BaseModel):
    total_open: int
    overdue: list[Commitment] = Field(default_factory=list)
    due_soon: list[Commitment] = Field(default_factory=list)   # within the next 48 hours
    other_open: list[Commitment] = Field(default_factory=list)


class CommitmentSummaryBuilder:
    """Answers "what have I promised people?" from real `Commitment`
    records only (rule 25/62) — grouped by urgency so the answer leads
    with what actually needs attention."""

    def build(self, commitments: list[Commitment]) -> CommitmentSummary:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        soon_cutoff = now + timedelta(hours=48)
        overdue = [c for c in commitments if c.status.value == "overdue"]
        due_soon = [c for c in commitments if c.status.value == "open" and c.deadline is not None and c.deadline <= soon_cutoff]
        other = [c for c in commitments if c.status.value == "open" and c not in due_soon]
        return CommitmentSummary(total_open=len(overdue) + len(due_soon) + len(other), overdue=overdue, due_soon=due_soon, other_open=other)
