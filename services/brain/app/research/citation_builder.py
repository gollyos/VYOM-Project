from __future__ import annotations

from .schemas import Claim, Source


class CitationBuilder:
    """Research conclusions must remain traceable. A claim without a
    supporting source is never cited and is instead marked uncertain."""

    def build(self, claims: list[Claim], sources: list[Source]) -> list[str]:
        source_by_id = {source.source_id: source for source in sources}
        citations: list[str] = []
        seen: set[str] = set()
        for claim in claims:
            if not claim.supporting_sources:
                continue
            for source_id in claim.supporting_sources:
                source = source_by_id.get(source_id)
                if source is None or source.source_id in seen:
                    continue
                seen.add(source.source_id)
                citations.append(f"{source.title} — {source.publisher} ({source.url})")
        return citations

    @staticmethod
    def mark_uncertain(claims: list[Claim]) -> list[Claim]:
        for claim in claims:
            if not claim.supporting_sources:
                claim.confidence = min(claim.confidence, 0.2)
        return claims
