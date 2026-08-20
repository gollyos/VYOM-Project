from __future__ import annotations

from dataclasses import dataclass, field

from .saas_discovery import SaaSCandidate, Subscription


@dataclass
class EvaluationScore:
    candidate: str
    score: float
    reasons: list[str] = field(default_factory=list)


class ToolEvaluator:
    """Comparison dimensions: capabilities, price, free tier, API
    availability, MCP availability, privacy, limits, integration effort,
    reliability."""

    def evaluate_saas(self, candidates: list[SaaSCandidate]) -> list[EvaluationScore]:
        scored = []
        for candidate in candidates:
            score = candidate.confidence
            reasons = [f"Evidence-derived confidence {candidate.confidence:.2f}"]
            if candidate.has_free_tier:
                score += 0.1
                reasons.append("Has a free tier")
            if candidate.has_api:
                score += 0.1
                reasons.append("Has an API")
            if candidate.has_mcp:
                score += 0.05
                reasons.append("Has an MCP integration")
            scored.append(EvaluationScore(candidate.name, round(min(1.0, score), 3), reasons))
        return sorted(scored, key=lambda item: item.score, reverse=True)

    @staticmethod
    def prefer_existing_subscription(need: str, subscriptions: list[Subscription]) -> Subscription | None:
        hint = need.lower()
        matches = [sub for sub in subscriptions if sub.status == "active" and any(hint in capability.lower() or capability.lower() in hint for capability in sub.capabilities)]
        return matches[0] if matches else None
