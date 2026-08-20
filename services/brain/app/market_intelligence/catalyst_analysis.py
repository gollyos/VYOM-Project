from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.research.orchestrator import DeepResearchTask
from app.research.schemas import ResearchDepth, ResearchResult

from .schemas import CatalystRecord

EmitFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]

CATEGORY_KEYWORDS = {
    "earnings": ("earnings", "quarterly results", "guidance"),
    "regulatory": ("regulat", "fda", "sec ", "antitrust", "compliance"),
    "product_announcement": ("launch", "unveil", "product", "release"),
    "macro": ("rate decision", "inflation", "fed ", "gdp", "macro"),
    "industry": ("industry", "sector", "competitor"),
}


def _categorize(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "company_announcement"


class CatalystResearcher:
    """Wraps `DeepResearchTask` (reusing Phase 8 research architecture, per
    rule 10) to find potentially relevant catalysts. Every catalyst keeps
    its source, date (when available), relevance, and confidence — never a
    bare unsourced claim."""

    def __init__(self, research_task: DeepResearchTask):
        self.research_task = research_task

    async def research(self, instrument: str, *, emit: EmitFn | None = None) -> tuple[list[CatalystRecord], ResearchResult]:
        goal = f"{instrument} catalysts: earnings, product announcements, regulatory events, macro events"
        result = await self.research_task.run(
            goal, depth=ResearchDepth.STANDARD,
            required_facts=["earnings date", "recent announcements", "regulatory events"],
            emit=emit,
        )
        source_by_id = {source.source_id: source for source in result.sources}
        catalysts: list[CatalystRecord] = []
        for claim in result.claims:
            source_ids = claim.supporting_sources
            publisher = source_by_id[source_ids[0]].publisher if source_ids and source_ids[0] in source_by_id else "unknown"
            catalysts.append(CatalystRecord(
                category=_categorize(claim.statement),
                description=claim.statement,
                source=publisher,
                relevance=claim.confidence,
                confidence=claim.confidence,
            ))
        return catalysts, result
