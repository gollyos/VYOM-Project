"""Trust Scoring for Memory — inspired by Jarvis/Atlas architecture.

Every memory has a trust grade (A/B/C/D) based on:
- Source priority (user correction > tool result > LLM inference)
- Confidence score
- Hit count (how often retrieved)
- Recency (decay over time)
- Supersession status

Grade A: Direct from user or verified tool — highest trust
Grade B: Inferred from multiple sources — good trust
Grade C: Single LLM inference — moderate trust
Grade D: Superseded or stale — lowest trust
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


# Source priority weights (higher = more trustworthy)
SOURCE_PRIORITY = {
    "user_correction": 1.0,     # User explicitly corrected this
    "user_instruction": 0.95,   # User explicitly stated this
    "tool_verified": 0.9,       # A real tool confirmed this
    "task_completed": 0.8,      # A task produced this as evidence
    "llm_inference": 0.5,       # LLM inferred this
    "llm_opinion": 0.3,         # LLM's opinion (no tool verification)
    "unknown": 0.2,             # Source unknown
}


@dataclass
class TrustGrade:
    """A graded trust assessment for a memory."""
    grade: str  # A | B | C | D
    score: float  # 0-1
    source_weight: float
    confidence_weight: float
    hit_count_weight: float
    recency_weight: float
    explanation: str


class TrustScorer:
    """Calculates trust grades for memories based on multiple signals."""

    # Decay half-life: memories lose trust over time
    DECAY_HALF_LIFE_DAYS = 90

    # Hit count bonus: frequently accessed memories gain trust
    HIT_BONUS_PER_ACCESS = 0.02
    MAX_HIT_BONUS = 0.3

    def score(
        self,
        source: str = "unknown",
        confidence: float = 0.5,
        hit_count: int = 0,
        created_at: str | None = None,
        superseded: bool = False,
        verification_state: str = "UNVERIFIED",
    ) -> TrustGrade:
        """Calculate trust grade for a memory."""

        # Source weight
        source_weight = SOURCE_PRIORITY.get(source, 0.2)

        # Confidence weight (direct from memory)
        confidence_weight = min(1.0, max(0.0, confidence))

        # Hit count weight (frequently accessed = more trusted)
        hit_bonus = min(self.MAX_HIT_BONUS, hit_count * self.HIT_BONUS_PER_ACCESS)
        hit_count_weight = hit_bonus

        # Recency weight (decay over time)
        recency_weight = 1.0
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_old = (now - created).total_seconds() / 86400
                recency_weight = max(0.1, 2 ** (-days_old / self.DECAY_HALF_LIFE_DAYS))
            except (ValueError, TypeError):
                recency_weight = 0.5

        # Superseded penalty
        if superseded or verification_state == "SUPERSEDED":
            source_weight *= 0.1
            confidence_weight *= 0.1

        # Verified bonus
        if verification_state == "VERIFIED":
            confidence_weight = min(1.0, confidence_weight + 0.2)

        # Combined score
        score = (
            source_weight * 0.35 +
            confidence_weight * 0.30 +
            hit_count_weight * 0.15 +
            recency_weight * 0.20
        )
        score = max(0.0, min(1.0, score))

        # Grade assignment
        if score >= 0.8:
            grade = "A"
        elif score >= 0.6:
            grade = "B"
        elif score >= 0.4:
            grade = "C"
        else:
            grade = "D"

        explanation_parts = []
        if source_weight >= 0.8:
            explanation_parts.append("high-trust source")
        elif source_weight <= 0.3:
            explanation_parts.append("low-trust source")
        if confidence_weight >= 0.7:
            explanation_parts.append("high confidence")
        if hit_count > 5:
            explanation_parts.append(f"frequently accessed ({hit_count}x)")
        if recency_weight < 0.5:
            explanation_parts.append("aging")
        if superseded:
            explanation_parts.append("superseded")

        return TrustGrade(
            grade=grade,
            score=score,
            source_weight=source_weight,
            confidence_weight=confidence_weight,
            hit_count_weight=hit_count_weight,
            recency_weight=recency_weight,
            explanation="; ".join(explanation_parts) if explanation_parts else "standard",
        )

    def filter_by_trust(self, memories: list[dict], min_grade: str = "C") -> list[dict]:
        """Filter memories to only those meeting a minimum trust grade."""
        grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        min_rank = grade_order.get(min_grade, 2)

        filtered = []
        for mem in memories:
            trust = self.score(
                source=mem.get("source", "unknown"),
                confidence=mem.get("confidence", 0.5),
                hit_count=mem.get("hit_count", 0),
                created_at=mem.get("created_at"),
                superseded=mem.get("superseded", False),
                verification_state=mem.get("verification_state", "UNVERIFIED"),
            )
            if grade_order.get(trust.grade, 3) <= min_rank:
                mem["trust_grade"] = trust.grade
                mem["trust_score"] = trust.score
                filtered.append(mem)

        return filtered

    def explain(self, memory: dict) -> str:
        """Generate a human-readable trust explanation for a memory."""
        trust = self.score(
            source=memory.get("source", "unknown"),
            confidence=memory.get("confidence", 0.5),
            hit_count=memory.get("hit_count", 0),
            created_at=memory.get("created_at"),
            superseded=memory.get("superseded", False),
            verification_state=memory.get("verification_state", "UNVERIFIED"),
        )
        return f"Grade {trust.grade} ({trust.score:.0%}): {trust.explanation}"
