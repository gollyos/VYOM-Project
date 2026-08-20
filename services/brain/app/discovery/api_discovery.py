from __future__ import annotations

from pydantic import BaseModel, Field

from app.research.orchestrator import DeepResearchTask, EmitFn
from app.research.schemas import ResearchDepth, SourceType


class APICandidate(BaseModel):
    service: str
    has_official_api: bool = False
    documentation_url: str | None = None
    pricing_notes: str = ""
    rate_limit_notes: str = ""
    required_permissions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class APIDiscovery:
    """If a service exposes an official API, VYOM prefers it over browser
    automation. Research is evidence-bound; nothing here fabricates
    endpoints or credentials."""

    def __init__(self, research_task: DeepResearchTask):
        self.research_task = research_task

    async def discover(self, service_name: str, *, emit: EmitFn | None = None) -> APICandidate:
        result = await self.research_task.run(
            f"Does {service_name} expose an official API?",
            depth=ResearchDepth.QUICK,
            required_facts=["authentication", "endpoints", "rate limits", "pricing", "documentation"],
            preferred_sources=[SourceType.OFFICIAL, SourceType.DOCUMENTATION],
            emit=emit,
        )
        official_sources = [source for source in result.sources if source.source_type in {SourceType.OFFICIAL, SourceType.DOCUMENTATION}]
        candidate = APICandidate(
            service=service_name,
            has_official_api=bool(official_sources),
            documentation_url=official_sources[0].url if official_sources else None,
            evidence=result.citations,
            confidence=result.confidence,
        )
        if emit:
            await emit("api_discovered", f"API discovery complete for {service_name}", {"has_official_api": candidate.has_official_api})
        return candidate
