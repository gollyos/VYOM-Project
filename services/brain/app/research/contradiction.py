from __future__ import annotations

import re

from .schemas import Claim, Contradiction, Source

NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*\.?\d*%?")


class ContradictionDetector:
    """If sources disagree, VYOM records the disagreement instead of
    silently picking one. See docs/RESEARCH_ARCHITECTURE.md."""

    def detect(self, claims: list[Claim], sources: list[Source]) -> list[Contradiction]:
        source_by_id = {source.source_id: source for source in sources}
        contradictions: list[Contradiction] = []
        grouped: dict[str, list[Claim]] = {}
        for claim in claims:
            grouped.setdefault(claim.required_fact or "general", []).append(claim)

        for fact, group in grouped.items():
            for index, claim_a in enumerate(group):
                numbers_a = NUMBER_PATTERN.findall(claim_a.statement)
                if not numbers_a:
                    continue
                for claim_b in group[index + 1:]:
                    numbers_b = NUMBER_PATTERN.findall(claim_b.statement)
                    if not numbers_b or set(numbers_a) == set(numbers_b):
                        continue
                    source_a = claim_a.supporting_sources[0] if claim_a.supporting_sources else "unknown"
                    source_b = claim_b.supporting_sources[0] if claim_b.supporting_sources else "unknown"
                    contradiction = Contradiction(
                        claim=fact,
                        source_a=source_a,
                        source_b=source_b,
                        difference=f"'{claim_a.statement[:80]}' vs '{claim_b.statement[:80]}'",
                        possible_reason="Sources may reference different time periods, regions, or plan tiers.",
                        recommended_interpretation="Prefer the more authoritative or fresher source; both are surfaced to the user.",
                        confidence=round(min(claim_a.confidence, claim_b.confidence), 3),
                    )
                    contradictions.append(contradiction)
                    claim_a.contradicting_sources.append(source_b)
                    claim_b.contradicting_sources.append(source_a)
                    if source_a in source_by_id:
                        source_by_id[source_a].conflicts.append(source_b)
                    if source_b in source_by_id:
                        source_by_id[source_b].conflicts.append(source_a)
        return contradictions
