from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


class DiscoveryQuery(BaseModel):
    goal: str


@router.post("/recommend")
async def recommend(payload: DiscoveryQuery, request: Request) -> dict:
    recommendation = await request.app.state.discovery_engine.discover(payload.goal)
    return {
        "goal": recommendation.goal,
        "has_existing_capability": recommendation.gap_report.has_existing_capability,
        "existing_subscription": recommendation.existing_subscription.model_dump(mode="json") if recommendation.existing_subscription else None,
        "saas_candidates": [asdict(item) for item in recommendation.saas_candidates],
        "api_candidate": recommendation.api_candidate.model_dump(mode="json") if recommendation.api_candidate else None,
        "mcp_candidates": [item.model_dump(mode="json") for item in recommendation.mcp_candidates],
        "recommendation": recommendation.recommendation,
    }
