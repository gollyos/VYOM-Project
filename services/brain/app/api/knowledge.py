from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
async def search_knowledge(q: str, request: Request, limit: int = 20) -> dict[str, Any]:
    """Recall facts VYOM already knows about `q` - the 'khud ka
    Wikipedia' lookup. Never triggers a browse/research pass itself;
    it just answers from what is already persisted (see
    KnowledgeService.recall)."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    result = await request.app.state.knowledge_service.recall(q, limit=min(max(limit, 1), 100))
    return result.model_dump(mode="json")


@router.get("/{topic}")
async def knowledge_for_topic(topic: str, request: Request, limit: int = 50) -> dict[str, Any]:
    """All known facts on a topic (exact/substring subject match)."""
    result = await request.app.state.knowledge_service.recall(topic, limit=min(max(limit, 1), 200))
    if not result.facts:
        raise HTTPException(status_code=404, detail=f"No knowledge recorded for '{topic}'")
    return result.model_dump(mode="json")
