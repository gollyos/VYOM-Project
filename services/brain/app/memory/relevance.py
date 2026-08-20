from __future__ import annotations

import math
from datetime import datetime, timezone

from .schemas import MemoryEntry, VerificationState


def relevance_score(
    memory: MemoryEntry,
    *,
    keyword_score: float,
    semantic_score: float,
    relationship_score: float = 0,
) -> tuple[float, list[str]]:
    age_days = max(0.0, (datetime.now(timezone.utc) - memory.updated_at).total_seconds() / 86400)
    recency = math.exp(-age_days / 120)
    verification = {
        VerificationState.VERIFIED: 1.0,
        VerificationState.INFERRED: 0.65,
        VerificationState.UNVERIFIED: 0.45,
        VerificationState.SUPERSEDED: 0.0,
    }[memory.verification_state]
    score = (
        keyword_score * 0.30
        + semantic_score * 0.24
        + memory.importance * 0.16
        + memory.confidence * 0.12
        + recency * 0.08
        + verification * 0.07
        + relationship_score * 0.03
    )
    reasons: list[str] = []
    if keyword_score > 0: reasons.append("keyword match")
    if semantic_score > 0.05: reasons.append("semantic similarity")
    if relationship_score > 0: reasons.append("relationship context")
    if memory.verification_state == VerificationState.VERIFIED: reasons.append("verified evidence")
    return score, reasons
