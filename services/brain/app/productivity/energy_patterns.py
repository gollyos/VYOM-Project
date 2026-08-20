from __future__ import annotations

from pydantic import BaseModel

from .focus_sessions import FocusSession
from .work_patterns import WorkPatternAnalyzer, WorkPatternInsight


class EnergyRecommendation(BaseModel):
    preferred_window: str | None = None
    stated_preference: str | None = None
    basis: str


class EnergyPatternService:
    """Combines the user's stated energy preference (from
    `PersonalProfile`) with real observed focus-session outcomes
    (`WorkPatternAnalyzer`). Never overrides a stated preference with an
    inference — it surfaces both, honestly labeled."""

    def __init__(self, analyzer: WorkPatternAnalyzer | None = None):
        self.analyzer = analyzer or WorkPatternAnalyzer()

    def recommend(self, sessions: list[FocusSession], stated_preference: str | None) -> EnergyRecommendation:
        insight: WorkPatternInsight | None = self.analyzer.best_start_window(sessions)
        if insight is not None:
            return EnergyRecommendation(preferred_window=insight.statement, stated_preference=stated_preference, basis="observed focus-session outcomes")
        if stated_preference:
            return EnergyRecommendation(preferred_window=None, stated_preference=stated_preference, basis="user-stated preference (no observed pattern yet)")
        return EnergyRecommendation(preferred_window=None, stated_preference=None, basis="insufficient data")
