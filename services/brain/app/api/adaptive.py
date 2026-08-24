from __future__ import annotations

from fastapi import APIRouter, Request

from app.memory.schemas import MemoryQuery, MemoryType


router = APIRouter(prefix="/api/adaptive", tags=["adaptive"])


@router.get("/lessons")
async def list_lessons(request: Request, limit: int = 20) -> dict:
    """Recent lessons the self-improvement loop actually stored (real
    MemoryType.LESSON entries in the same durable memory store every
    other Brain recall reads from — never a synthetic report)."""
    memory_manager = request.app.state.memory_manager
    results = await memory_manager.search(
        MemoryQuery(text="", types={MemoryType.LESSON}, limit=min(max(limit, 1), 100))
    )
    return {
        "lessons": [
            {
                "id": item.memory.id,
                "title": item.memory.title,
                "content": item.memory.content,
                "confidence": item.memory.confidence,
                "task_id": item.memory.task_id,
                "created_at": item.memory.created_at.isoformat(),
            }
            for item in results
        ],
        "count": len(results),
    }


@router.get("/router-bias")
async def router_bias(request: Request, domain: str | None = None) -> dict:
    """The LIVE learned-router bias state: per-model, per-domain
    aggregate performance and the exact bias score the ModelRouter adds
    to that model's routing score right now. Reads the SAME
    AdaptiveLearner.model_performance() the router itself consults on
    every route() call — this is not a separate, possibly-stale report."""
    learned_router = getattr(request.app.state, "learned_router", None)
    if learned_router is None:
        return {"attached": False, "models": {}}
    performance = await learned_router.learner.model_performance()
    models: dict[str, dict] = {}
    for model_id, stats in performance.items():
        domains = stats.get("domains", {})
        domain_keys = [domain] if domain else list(domains.keys())
        biases = {}
        for key in domain_keys:
            bias, reason = learned_router.model_bias(model_id, key, performance)
            if reason:
                biases[key] = {"bias": bias, "reason": reason}
        models[model_id] = {
            "success_rate": stats.get("success_rate"),
            "calls": stats.get("calls"),
            "domain_bias": biases,
        }
    return {"attached": True, "models": models}
