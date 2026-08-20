from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.research.schemas import Freshness, ResearchDepth, ResearchResult

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchQuery(BaseModel):
    goal: str
    depth: ResearchDepth | None = None
    required_facts: list[str] = []
    freshness_requirement: Freshness = Freshness.UNKNOWN


@router.post("/run", response_model=ResearchResult)
async def run_research(payload: ResearchQuery, request: Request) -> ResearchResult:
    try:
        return await request.app.state.research_task.run(
            payload.goal, depth=payload.depth, required_facts=payload.required_facts or None,
            freshness_requirement=payload.freshness_requirement,
        )
    except Exception as error:  # research is best-effort/evidence-bound, never silently fails as success
        raise HTTPException(status_code=502, detail=str(error)) from error
