from __future__ import annotations

from pydantic import BaseModel, Field


class WeeklyReviewInput(BaseModel):
    wins: list[str] = Field(default_factory=list)
    unfinished_commitments: list[str] = Field(default_factory=list)
    goal_progress_notes: list[str] = Field(default_factory=list)
    client_status_notes: list[str] = Field(default_factory=list)
    habit_trend_notes: list[str] = Field(default_factory=list)
    focus_trend_notes: list[str] = Field(default_factory=list)
    model_agent_performance_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_week_priorities: list[str] = Field(default_factory=list)


class WeeklyReview(BaseModel):
    summary: str
    sections: dict[str, list[str]]


class WeeklyReviewService:
    def build(self, data: WeeklyReviewInput) -> WeeklyReview:
        sections = {
            "wins": data.wins, "unfinished": data.unfinished_commitments, "goal_progress": data.goal_progress_notes,
            "client_status": data.client_status_notes, "habit_trends": data.habit_trend_notes,
            "focus_trends": data.focus_trend_notes, "agent_performance": data.model_agent_performance_notes,
            "risks": data.risks, "next_week_priorities": data.next_week_priorities,
        }
        summary = f"Weekly review: {len(data.wins)} win(s), {len(data.unfinished_commitments)} unfinished commitment(s), {len(data.risks)} risk(s) noted."
        return WeeklyReview(summary=summary, sections={key: value for key, value in sections.items() if value})
