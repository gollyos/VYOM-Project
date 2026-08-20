from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, ResearchResult, SourceType


async def research_company(
    task: DeepResearchTask,
    company_name: str,
    *,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    return await task.run(
        f"Company profile of {company_name}",
        depth=depth,
        required_facts=["overview", "leadership", "funding", "products", "recent news"],
        preferred_sources=[SourceType.OFFICIAL, SourceType.COMPANY, SourceType.NEWS],
        emit=emit,
    )
