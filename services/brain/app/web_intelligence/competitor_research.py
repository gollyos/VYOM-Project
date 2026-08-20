from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, ResearchResult, SourceType


async def research_competitor(
    task: DeepResearchTask,
    competitor_name: str,
    *,
    against: str | None = None,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    goal = f"Competitive profile of {competitor_name}"
    if against:
        goal += f" compared to {against}"
    return await task.run(
        goal,
        depth=depth,
        required_facts=["pricing", "core features", "market positioning", "target customers", "differentiators"],
        preferred_sources=[SourceType.COMPANY, SourceType.NEWS, SourceType.RESEARCH_PAPER],
        emit=emit,
    )
