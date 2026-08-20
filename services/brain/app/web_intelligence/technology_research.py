from __future__ import annotations

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, ResearchResult, SourceType


async def research_technology(
    task: DeepResearchTask,
    technology_name: str,
    *,
    depth: ResearchDepth | None = None,
    emit: EmitFn | None = None,
) -> ResearchResult:
    return await task.run(
        f"Technology research for {technology_name}",
        depth=depth,
        required_facts=["how it works", "official documentation", "known limitations", "alternatives"],
        preferred_sources=[SourceType.OFFICIAL, SourceType.DOCUMENTATION],
        emit=emit,
    )
