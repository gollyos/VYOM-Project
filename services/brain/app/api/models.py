from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models(request: Request) -> dict:
    registry = request.app.state.model_registry
    providers = request.app.state.providers
    health = request.app.state.provider_health
    provider_status = []
    for provider in providers.all():
        check = await provider.health_check()
        check["available"] = bool(check["available"] and health.available(provider.name))
        check["recent_failures"] = health.recent_failure_count(provider.name)
        provider_status.append(check)
    return {
        "models": [model.model_dump(mode="json") for model in registry.models],
        "providers": provider_status,
    }

