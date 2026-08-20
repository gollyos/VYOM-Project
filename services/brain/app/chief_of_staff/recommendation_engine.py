from __future__ import annotations

from pydantic import BaseModel, Field

from .priority_engine import PriorityScore


class Recommendation(BaseModel):
    action: str
    reason: str
    estimated_minutes: float | None = None


class RecommendationResult(BaseModel):
    primary: Recommendation | None
    alternatives: list[Recommendation] = Field(default_factory=list)


class RecommendationEngine:
    """Prefers one recommended action plus at most two alternatives
    (rule 69) — never a long list of options unless the caller explicitly
    asks for more."""

    def recommend(self, ranked: list[PriorityScore], *, max_alternatives: int = 2) -> RecommendationResult:
        if not ranked:
            return RecommendationResult(primary=None, alternatives=[])
        top = ranked[0]
        primary = Recommendation(
            action=top.label,
            reason="; ".join(top.reasons) if top.reasons else "highest combined priority",
            estimated_minutes=top.effort_minutes,
        )
        alternatives = [
            Recommendation(action=item.label, reason="; ".join(item.reasons) if item.reasons else "next highest priority", estimated_minutes=item.effort_minutes)
            for item in ranked[1: 1 + max_alternatives]
        ]
        return RecommendationResult(primary=primary, alternatives=alternatives)
