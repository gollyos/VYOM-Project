from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, ResearchResult, SourceType


async def research_market(
    task: DeepResearchTask,
    market_name: str,
    *,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    return await task.run(
        f"Market analysis for {market_name}",
        depth=depth or ResearchDepth.DEEP,
        required_facts=["market size", "growth rate", "key players", "trends"],
        preferred_sources=[SourceType.RESEARCH_PAPER, SourceType.GOVERNMENT, SourceType.NEWS],
        emit=emit,
    )
