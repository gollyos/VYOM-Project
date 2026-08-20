from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def system_health(request: Request) -> dict:
    aggregator = request.app.state.health_aggregator
    return await aggregator.assess()


@router.get("/recovery")
async def recovery_decisions(request: Request) -> dict:
    """The crash-recovery decisions made at Brain startup: which
    interrupted tasks were resumed, retried, paused, or flagged for
    review."""
    return {"decisions": getattr(request.app.state, "last_recovery_decisions", [])}


@router.get("/metrics")
async def reliability_metrics(request: Request) -> dict:
    return request.app.state.reliability_metrics.snapshot()


@router.get("/circuit-breakers")
async def circuit_breakers(request: Request) -> list[dict]:
    registry = request.app.state.circuit_breakers
    keys = sorted(registry._breakers.keys())  # noqa: SLF001 — read-only introspection endpoint
    return [registry.status(key) for key in keys]


@router.get("/checkpoints/{task_id}")
async def task_checkpoint(task_id: str, request: Request) -> dict:
    checkpoints = request.app.state.checkpoint_store
    checkpoint = await checkpoints.get(task_id)
    return {"task_id": task_id, "checkpoint": checkpoint.model_dump(mode="json") if checkpoint else None}


@router.get("/budgets")
async def budgets(request: Request) -> dict:
    manager = request.app.state.budget_manager
    usage = await manager.usage()
    return {
        "usage": usage,
        "limits": {
            "daily_model_cost": manager.limits.daily_model_cost,
            "daily_research_calls": manager.limits.daily_research_calls,
            "max_concurrent_tasks": manager.limits.max_concurrent_tasks,
            "max_active_agents": manager.limits.max_active_agents,
            "max_browser_sessions": manager.limits.max_browser_sessions,
        },
    }
