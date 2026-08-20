from __future__ import annotations

from pydantic import BaseModel, Field


class MonthlyReviewInput(BaseModel):
    business_growth_notes: list[str] = Field(default_factory=list)
    client_acquisition_notes: list[str] = Field(default_factory=list)
    project_progress_notes: list[str] = Field(default_factory=list)
    habit_consistency_notes: list[str] = Field(default_factory=list)
    learning_notes: list[str] = Field(default_factory=list)
    personal_goal_notes: list[str] = Field(default_factory=list)
    ai_spend_notes: list[str] = Field(default_factory=list)
    agent_productivity_notes: list[str] = Field(default_factory=list)
    paper_trading_notes: list[str] = Field(default_factory=list)


class MonthlyReview(BaseModel):
    summary: str
    sections: dict[str, list[str]]


class MonthlyReviewService:
    """Focuses on longer-term trends (rule 42) — bounded sections, not a
    metrics dump. `paper_trading_notes` only appears when Phase 10 paper
    trading is actually in use."""

    def build(self, data: MonthlyReviewInput) -> MonthlyReview:
        sections = {
            "business_growth": data.business_growth_notes, "client_acquisition": data.client_acquisition_notes,
            "project_progress": data.project_progress_notes, "habit_consistency": data.habit_consistency_notes,
            "learning": data.learning_notes, "personal_goals": data.personal_goal_notes,
            "ai_spend": data.ai_spend_notes, "agent_productivity": data.agent_productivity_notes,
            "paper_trading": data.paper_trading_notes,
        }
        non_empty = {key: value for key, value in sections.items() if value}
        summary = f"Monthly review covering {len(non_empty)} area(s) with recorded activity."
        return MonthlyReview(summary=summary, sections=non_empty)
