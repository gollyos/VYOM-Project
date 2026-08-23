from __future__ import annotations

from .schemas import Claim, Contradiction, ResearchPlan


class ResearchSynthesizer:
    """Synthesis of extracted research claims.

    The deterministic template always remains available so research
    never depends on a model to produce a result. When the caller wires
    a model provider, `synthesize_async` asks it to write the synthesis
    from the SAME extracted claims (never from the model's own
    knowledge), with the deterministic text as fallback. Repeated
    identical syntheses hit the shared response cache, not the quota.
    """

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

    async def synthesize_async(
        self,
        plan: ResearchPlan,
        claims: list[Claim],
        contradictions: list[Contradiction],
        gaps: list[str],
        *,
        provider=None,
        model: str | None = None,
    ) -> str:
        """LLM synthesis over extracted claims; deterministic fallback.

        The model may only ARRANGE the evidence below - the prompt lists
        every claim with its confidence and sources and forbids adding
        facts that are not among them."""
        fallback = self.synthesize(plan, claims, contradictions, gaps)
        if provider is None or model is None:
            return fallback
        supported = [claim for claim in claims if claim.supporting_sources]
        if not supported:
            return fallback
        evidence = "\n".join(
            f"- {claim.statement} (confidence {claim.confidence:.2f}, sources: {len(claim.supporting_sources)})"
            for claim in sorted(supported, key=lambda item: item.confidence, reverse=True)[:15]
        )
        contradiction_text = "; ".join(
            f"{item.left_claim_id} vs {item.right_claim_id}" for item in contradictions[:5]
        ) or "none"
        prompt = (
            f"Research goal: {plan.goal}\n\n"
            f"Extracted evidence (use ONLY these facts, arrange and word them "
            f"clearly; do not add anything else):\n{evidence}\n\n"
            f"Contradictions to surface honestly: {contradiction_text}\n"
            f"Open gaps: {'; '.join(gaps) or 'none'}\n\n"
            "Write a concise synthesis in the user's language (they often "
            "write Hinglish). 5-10 lines, no invented facts."
        )
        try:
            from app.providers.base import ProviderRequest
            from app.schemas.tasks import TaskProfile

            request = ProviderRequest(
                model=model,
                user_request=prompt,
                system_instruction="You synthesise research findings. Only restate the given evidence.",
                profile=TaskProfile(needs={"reasoning"}),
            )
            response = await provider.structured_output(request)
        except Exception:
            return fallback
        text = (response.text or "").strip()
        return text if len(text) >= len(fallback) // 4 else fallback
