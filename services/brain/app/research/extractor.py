from __future__ import annotations

import re

from .schemas import Claim, ResearchPlan, Source, VerificationState


class ClaimExtractor:
    """Turns read sources into traceable claims. Every claim keeps a
    supporting_sources link back to the source it came from."""

    def extract(self, sources: list[Source], plan: ResearchPlan) -> list[Claim]:
        claims: list[Claim] = []
        facts = plan.required_facts or [plan.goal]
        for source in sources:
            statement = (source.excerpt or source.title).strip()
            if not statement:
                continue
            required_fact = self._match_fact(statement, facts)
            claim = Claim(
                statement=statement[:500],
                confidence=round(min(1.0, 0.25 + source.trust_score * 0.5 + source.relevance_score * 0.25), 3),
                supporting_sources=[source.source_id],
                freshness=source.freshness,
                verification_state=VerificationState.INFERRED,
                required_fact=required_fact,
            )
            claims.append(claim)
            source.claims_supported.append(claim.claim_id)
        return claims

    @staticmethod
    def _match_fact(statement: str, facts: list[str]) -> str:
        statement_tokens = set(re.findall(r"[a-z0-9]+", statement.lower()))
        best_fact, best_overlap = facts[0], -1
        for fact in facts:
            fact_tokens = set(re.findall(r"[a-z0-9]+", fact.lower()))
            overlap = len(statement_tokens & fact_tokens)
            if overlap > best_overlap:
                best_fact, best_overlap = fact, overlap
        return best_fact
