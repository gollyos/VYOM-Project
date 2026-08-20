from __future__ import annotations

from .schemas import ResearchResult, VerificationState


class ResearchVerifier:
    """A completed research task is not the same as a verified one."""

    def verify(self, result: ResearchResult) -> ResearchResult:
        checks = {
            "has_sources": bool(result.sources),
            "unsupported_claims_are_low_confidence": all(
                bool(claim.supporting_sources) or claim.confidence <= 0.2 for claim in result.claims
            ),
            "within_source_budget": len(result.sources) <= result.plan.budget.max_sources,
            "citations_traceable": all(
                claim.supporting_sources or claim.confidence <= 0.2 for claim in result.claims
            ),
        }
        if not checks["has_sources"] and "No sources were available for this goal" not in result.gaps:
            result.gaps.append("No sources were available for this goal")

        result.confidence = (
            round(sum(claim.confidence for claim in result.claims) / len(result.claims), 3)
            if result.claims else 0.0
        )
        result.verification_state = (
            VerificationState.VERIFIED if all(checks.values()) else VerificationState.UNVERIFIED
        )
        return result
