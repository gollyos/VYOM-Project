from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, ResearchResult, SourceType


async def research_product(
    task: DeepResearchTask,
    product_name: str,
    *,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    return await task.run(
        f"Product research for {product_name}",
        depth=depth,
        required_facts=["features", "pricing", "reviews", "alternatives"],
        preferred_sources=[SourceType.OFFICIAL, SourceType.COMPANY, SourceType.COMMUNITY],
        emit=emit,
    )
