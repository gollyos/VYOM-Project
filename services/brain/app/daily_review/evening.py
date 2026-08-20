from __future__ import annotations

from pydantic import BaseModel, Field


class EveningReviewInput(BaseModel):
    """Only real recorded events (rule 39/40) — a task, meeting, or focus
    session must have actually completed/occurred to appear here."""

    tasks_completed: list[str] = Field(default_factory=list)
    verified_work: list[str] = Field(default_factory=list)
    meetings_held: list[str] = Field(default_factory=list)
    commitments_completed: list[str] = Field(default_factory=list)
    commitments_open: list[str] = Field(default_factory=list)
    goal_progress_notes: list[str] = Field(default_factory=list)
    focus_session_minutes: float = 0.0
    best_focus_window: str | None = None
    missed_priorities: list[str] = Field(default_factory=list)
    tomorrow_recommendation: str | None = None


class EveningReview(BaseModel):
    summary: str
    completed: list[str]
    open_items: list[str]
    pattern_note: str | None
    tomorrow: str | None


class EveningReviewService:
    """"How did today go?" (rule 39/40) — assembled only from real
    recorded events; never a fabricated accomplishment list."""

    def build(self, data: EveningReviewInput) -> EveningReview:
        completed = [*data.tasks_completed, *data.verified_work, *data.meetings_held, *data.commitments_completed]
        if data.focus_session_minutes:
            completed.append(f"{data.focus_session_minutes / 60:.1f} hour(s) of deep work")

        pattern_note = f"Your best focus block was {data.best_focus_window}." if data.best_focus_window else None

        if not completed and not data.missed_priorities:
            summary = "No recorded activity for today yet."
        else:
            summary = f"Today: {len(completed)} meaningful item(s) recorded."
            if data.commitments_open:
                summary += f" {len(data.commitments_open)} commitment(s) still open."

        return EveningReview(
            summary=summary, completed=completed, open_items=[*data.commitments_open, *data.missed_priorities],
            pattern_note=pattern_note, tomorrow=data.tomorrow_recommendation,
        )
