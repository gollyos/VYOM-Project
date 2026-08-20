from __future__ import annotations

from .schemas import Claim, Contradiction, ResearchPlan


class ResearchSynthesizer:
    """Deterministic template synthesis. When a capable model/provider is
    routed by the caller, its structured output may replace this text; the
    deterministic path always remains available so research never depends
    on a paid model to produce a result."""

    def synthesize(
        self,
        plan: ResearchPlan,
        claims: list[Claim],
        contradictions: list[Contradiction],
        gaps: list[str],
    ) -> str:
        supported = [claim for claim in claims if claim.supporting_sources]
        lines = [f"Research synthesis for: {plan.goal}"]
        if supported:
            lines.append("Key findings:")
            for claim in sorted(supported, key=lambda item: item.confidence, reverse=True)[:6]:
                lines.append(f"- {claim.statement} (confidence {claim.confidence:.2f})")
        else:
            lines.append("No sufficiently supported findings were extracted from available sources.")
        if contradictions:
            lines.append(f"{len(contradictions)} contradiction(s) were found between sources and are not silently resolved.")
        if gaps:
            lines.append("Open gaps: " + "; ".join(gaps))
        return "\n".join(lines)
