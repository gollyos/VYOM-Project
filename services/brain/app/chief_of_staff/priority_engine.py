from __future__ import annotations

from pydantic import BaseModel, Field

# Weights are explicit and documented (rule 27) — never an opaque single
# number with no explanation.
_WEIGHTS = {
    "urgency": 0.22, "importance": 0.18, "goal_alignment": 0.14, "client_impact": 0.16,
    "financial_impact": 0.1, "dependency": 0.12, "risk": 0.08,
}


class PrioritySignal(BaseModel):
    item_id: str
    label: str
    urgency: float = Field(default=0.0, ge=0, le=1)
    importance: float = Field(default=0.0, ge=0, le=1)
    goal_alignment: float = Field(default=0.0, ge=0, le=1)
    client_impact: float = Field(default=0.0, ge=0, le=1)
    financial_impact: float = Field(default=0.0, ge=0, le=1)
    dependency: float = Field(default=0.0, ge=0, le=1)  # how much other work is blocked on this
    risk: float = Field(default=0.0, ge=0, le=1)
    effort_minutes: float | None = None
    user_preference_bonus: float = Field(default=0.0, ge=0, le=0.2)


class PriorityScore(BaseModel):
    item_id: str
    label: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    effort_minutes: float | None = None


class PriorityEngine:
    """Combines urgency/importance/goal-alignment/client-impact/financial-
    impact/dependency/risk/user-preference into a score, but always
    returns the top contributing reasons alongside it (rule 27) — never a
    bare opaque number."""

    def score(self, signal: PrioritySignal) -> PriorityScore:
        contributions = {factor: getattr(signal, factor) * weight for factor, weight in _WEIGHTS.items()}
        total = sum(contributions.values()) + signal.user_preference_bonus
        ranked_factors = sorted(contributions.items(), key=lambda item: item[1], reverse=True)
        reasons = [self._explain(factor, getattr(signal, factor)) for factor, contribution in ranked_factors[:3] if getattr(signal, factor) > 0]
        if signal.user_preference_bonus > 0:
            reasons.append("matches a stated user preference")
        return PriorityScore(item_id=signal.item_id, label=signal.label, score=round(total, 4), reasons=reasons, effort_minutes=signal.effort_minutes)

    def rank(self, signals: list[PrioritySignal]) -> list[PriorityScore]:
        return sorted((self.score(signal) for signal in signals), key=lambda score: score.score, reverse=True)

    @staticmethod
    def _explain(factor: str, value: float) -> str:
        labels = {
            "urgency": "time-sensitive", "importance": "important", "goal_alignment": "advances a goal",
            "client_impact": "affects a client", "financial_impact": "has financial impact",
            "dependency": "blocks other work", "risk": "carries risk if delayed",
        }
        return labels.get(factor, factor)
