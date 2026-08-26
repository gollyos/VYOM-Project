from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/conversation", tags=["conversation"])


@router.get("/search")
async def search_conversation(request: Request, q: str, context_id: str | None = None, limit: int = 20) -> dict:
    """Full-text search over the raw turn-by-turn transcript (see
    app/persistence/conversation_store.py) - the answer to 'what did I
    say about X', distinct from searching structured task rows or
    curated memory facts."""
    store = request.app.state.conversation_store
    turns = await store.search(q, context_id=context_id, limit=min(max(limit, 1), 100))
    return {"count": len(turns), "turns": [t.model_dump(mode="json") for t in turns]}


@router.get("/history")
async def conversation_history(request: Request, context_id: str, limit: int = 50) -> dict:
    """Recent turns for one context, oldest first (reading order)."""
    store = request.app.state.conversation_store
    turns = await store.history(context_id, limit=min(max(limit, 1), 200))
    return {"count": len(turns), "turns": [t.model_dump(mode="json") for t in turns]}
