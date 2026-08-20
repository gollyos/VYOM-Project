from __future__ import annotations

from app.research.schemas import Claim

from .schemas import SentimentAssessment

POSITIVE_WORDS = {"beat", "beats", "growth", "record", "surge", "upgrade", "strong", "expansion", "outperform", "raises"}
NEGATIVE_WORDS = {"miss", "misses", "decline", "lawsuit", "downgrade", "weak", "investigation", "recall", "cuts", "warns"}


class SentimentAnalyzer:
    """Deterministic keyword-heuristic sentiment over extracted research
    claims. Always labeled `method="heuristic-keyword"` — never presented
    as a trained sentiment model (honesty matches the local-fixture
    labeling pattern used elsewhere)."""

    def analyze(self, claims: list[Claim]) -> SentimentAssessment | None:
        if not claims:
            return None
        score_total = 0
        for claim in claims:
            text = claim.statement.lower()
            score_total += sum(1 for word in POSITIVE_WORDS if word in text)
            score_total -= sum(1 for word in NEGATIVE_WORDS if word in text)
        normalized = max(-1.0, min(1.0, score_total / max(len(claims), 1)))
        if normalized > 0.15:
            label = "positive"
        elif normalized < -0.15:
            label = "negative"
        elif abs(normalized) <= 0.05:
            label = "neutral"
        else:
            label = "mixed"
        return SentimentAssessment(
            label=label, score=round(normalized, 4), sample_size=len(claims),
            rationale=f"Keyword heuristic over {len(claims)} extracted claim(s); not a trained sentiment model.",
        )
