from __future__ import annotations

from pydantic import BaseModel, Field

from .focus_sessions import FocusSession, FocusSessionResult


class WorkPatternInsight(BaseModel):
    statement: str
    sample_size: int
    confidence: float = Field(ge=0, le=1)


class WorkPatternAnalyzer:
    """Finds real completion-rate differences by focus-session start time
    (rule 12 example: "sessions complete more when started before
    10:30"). Requires a minimum sample per bucket before comparing
    buckets, so a lucky morning isn't presented as a rule (rule 13)."""

    def __init__(self, *, minimum_sample_per_bucket: int = 3):
        self.minimum_sample_per_bucket = minimum_sample_per_bucket

    def best_start_window(self, sessions: list[FocusSession]) -> WorkPatternInsight | None:
        completed = [s for s in sessions if s.result is not None]
        if len(completed) < self.minimum_sample_per_bucket * 2:
            return None

        buckets: dict[str, list[FocusSession]] = {"before 10:30": [], "10:30-14:00": [], "after 14:00": []}
        for session in completed:
            hour, minute = session.start.hour, session.start.minute
            if hour < 10 or (hour == 10 and minute <= 30):
                buckets["before 10:30"].append(session)
            elif hour < 14:
                buckets["10:30-14:00"].append(session)
            else:
                buckets["after 14:00"].append(session)

        rates: dict[str, float] = {}
        for label, items in buckets.items():
            if len(items) < self.minimum_sample_per_bucket:
                continue
            success = sum(1 for s in items if s.result == FocusSessionResult.COMPLETED)
            rates[label] = success / len(items)

        if len(rates) < 2:
            return None
        best_label, best_rate = max(rates.items(), key=lambda item: item[1])
        other_rates = [rate for label, rate in rates.items() if label != best_label]
        baseline = sum(other_rates) / len(other_rates)
        if baseline <= 0 or best_rate <= baseline:
            return None
        lift_pct = round(((best_rate - baseline) / baseline) * 100, 1)
        return WorkPatternInsight(
            statement=f"Focus sessions starting {best_label} complete {lift_pct}% more often than sessions starting at other times",
            sample_size=len(completed), confidence=round(best_rate, 4),
        )
