from __future__ import annotations

import re
from typing import Any

from .schemas import ResearchPlan, Source, SourceType

DEFAULT_TRUST_WEIGHTS: dict[SourceType, float] = {
    SourceType.OFFICIAL: 0.95,
    SourceType.GOVERNMENT: 0.95,
    SourceType.DOCUMENTATION: 0.9,
    SourceType.RESEARCH_PAPER: 0.85,
    SourceType.DATABASE: 0.75,
    SourceType.COMPANY: 0.65,
    SourceType.NEWS: 0.55,
    SourceType.COMMUNITY: 0.4,
    SourceType.SOCIAL: 0.25,
    SourceType.UNKNOWN: 0.2,
}


class SourceRanker:
    """Not all web pages are equal. See docs/SOURCE_TRUST_POLICY.md."""

    def __init__(self, trust_weights: dict[SourceType, float] | None = None):
        self.trust_weights = trust_weights or DEFAULT_TRUST_WEIGHTS

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SourceRanker":
        raw_weights = config.get("trust_weights", {})
        weights = dict(DEFAULT_TRUST_WEIGHTS)
        for key, value in raw_weights.items():
            try:
                weights[SourceType(key)] = float(value)
            except ValueError:
                continue
        return cls(weights)

    def rank(self, sources: list[Source], plan: ResearchPlan) -> list[Source]:
        tokens = set(re.findall(r"[a-z0-9]+", " ".join([plan.goal, *plan.questions, *plan.required_facts]).lower()))
        ranked: list[Source] = []
        for source in sources:
            trust = self.trust_weights.get(source.source_type, 0.2)
            if plan.preferred_sources and source.source_type in plan.preferred_sources:
                trust = min(1.0, trust + 0.1)
            haystack_tokens = set(re.findall(r"[a-z0-9]+", f"{source.title} {source.excerpt} {source.publisher}".lower()))
            overlap = len(tokens & haystack_tokens)
            relevance = min(1.0, overlap / max(1, len(tokens)) * 3)
            source.trust_score = round(trust, 3)
            source.relevance_score = round(relevance, 3)
            source.primary_or_secondary = "primary" if source.source_type in {
                SourceType.OFFICIAL, SourceType.GOVERNMENT, SourceType.RESEARCH_PAPER,
            } else "secondary"
            ranked.append(source)
        return sorted(ranked, key=lambda item: (item.trust_score * 0.6 + item.relevance_score * 0.4), reverse=True)
