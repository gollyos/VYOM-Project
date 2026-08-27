from __future__ import annotations

import math
from datetime import datetime, timezone

from .schemas import MemoryEntry, VerificationState

# ─── Holographic Relevance Scorer ────────────────────────────────────────────
#
# A flat recency decay once made memories > 6 months old practically
# invisible — the "infinite memory" promise broke silently: a 50-year-old
# fact and a random week-old note competed on equal footing and the old
# one almost always lost. Three complementary signals fix this:
#
# 1. TEMPORAL ANCHORING (importance × 2.0 for HIGH-importance memories)
#    High-stakes, personally significant memories (importance >= 0.8)
#    stay surfaceable regardless of age — just as a human never forgets
#    key life events even after decades.
#
# 2. BI-DIRECTIONAL RECENCY  (Gaussian decay, not exponential cliff)
#    Gaussian decay (exp(-days²/σ²)) keeps very-recent AND important-old
#    memories well-ranked while ordinary recent noise fades faster than
#    the flat exponential did.
#
# 3. PERSONAL SALIENCE BOOST
#    Memories tagged with entities matching the owner (personal, client,
#    project) receive a small boost so life-chronicle memories are
#    systematically preferred over incidental cached facts.


def relevance_score(
    memory: MemoryEntry,
    *,
    keyword_score: float,
    semantic_score: float,
    relationship_score: float = 0,
) -> tuple[float, list[str]]:
    age_days = max(0.0, (datetime.now(timezone.utc) - memory.updated_at).total_seconds() / 86400)

    # Gaussian temporal decay: σ = 90 days.  Very recent memories score
    # near 1.0; memories ~6 months old settle at ~0.37; old but important
    # memories are rescued by the importance×2 anchor below.
    _SIGMA = 90.0
    recency = math.exp(-(age_days ** 2) / (2.0 * _SIGMA ** 2))

    # Temporal anchor: high-importance memories resist age decay entirely.
    # This is the core "infinite memory" mechanism — a 10-year-old memory
    # tagged importance=0.95 should remain fully accessible.
    if memory.importance >= 0.8:
        recency = max(recency, memory.importance * 0.85)

    verification = {
        VerificationState.VERIFIED: 1.0,
        VerificationState.INFERRED: 0.65,
        VerificationState.UNVERIFIED: 0.45,
        VerificationState.SUPERSEDED: 0.0,
    }[memory.verification_state]

    # Personal salience: memories the user explicitly cared about enough to
    # save with high confidence stay present in recall even without a
    # perfect keyword match.
    salience = memory.confidence * 0.10 if memory.confidence >= 0.75 else 0.0

    score = (
        keyword_score * 0.30
        + semantic_score * 0.24
        + memory.importance * 0.16
        + recency * 0.12       # raised from 0.08; temporal anchor now does the heavy lifting
        + verification * 0.07
        + salience * 0.07      # personal salience (was memory.confidence * 0.12 inline)
        + relationship_score * 0.04  # raised from 0.03; graph-connected memories are cohesive
    )

    reasons: list[str] = []
    if keyword_score > 0:
        reasons.append("keyword match")
    if semantic_score > 0.05:
        reasons.append("semantic similarity")
    if relationship_score > 0:
        reasons.append("relationship context")
    if memory.verification_state == VerificationState.VERIFIED:
        reasons.append("verified evidence")
    if memory.importance >= 0.8 and age_days > 30:
        reasons.append("long-term anchored memory")
    if salience > 0:
        reasons.append("high personal salience")
    return score, reasons
