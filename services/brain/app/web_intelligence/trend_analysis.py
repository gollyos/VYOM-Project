from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import Freshness, ResearchDepth, ResearchResult, SourceType


async def research_trend(
    task: DeepResearchTask,
    trend_topic: str,
    *,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    return await task.run(
        f"Current trend analysis for {trend_topic}",
        depth=depth,
        required_facts=["current direction", "recent data points", "expert commentary"],
        preferred_sources=[SourceType.NEWS, SourceType.RESEARCH_PAPER],
        freshness_requirement=Freshness.FRESH,
        emit=emit,
    )
