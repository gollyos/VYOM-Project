from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.persistence.database import Database
from app.persistence.model_performance_store import ModelPerformanceStore
from app.persistence.task_store import TaskStore
from app.providers.base import ProviderRegistry
from app.providers.deterministic import DeterministicProvider
from app.routing.model_registry import ModelRegistry
from app.routing.model_router import ModelRouter
from app.routing.provider_health import ProviderHealth
from app.routing.usage_tracker import UsageTracker
from app.runtime.event_bus import EventBus
from app.runtime.executor import Executor
from app.runtime.planner import Planner
from app.runtime.task_classifier import TaskClassifier
from app.runtime.task_runtime import TaskRuntime
from app.runtime.verifier import Verifier
from app.schemas.routing import ModelDefinition
from app.schemas.tasks import Task, TaskStatus
from app.security.permission_engine import PermissionEngine


def local_model(provider: str = "local", model_id: str = "local-rules-v1", **updates) -> ModelDefinition:
    values = {
        "provider": provider,
        "model_id": model_id,
        "enabled": True,
        "capabilities": {"general", "planning", "structured_output"},
        "quality_tier": "basic",
        "speed_tier": "instant",
        "cost_tier": "free",
        "context_tier": "small",
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "privacy_policy": "local_only",
        "priority": 100,
    }
    values.update(updates)
    return ModelDefinition.model_validate(values)


class MockProvider(DeterministicProvider):
    def __init__(self, name: str, delay_seconds: float = 0):
        super().__init__(delay_seconds)
        self.name = name


async def build_runtime(
    database_path: Path,
    *,
    models: list[ModelDefinition] | None = None,
    providers: list | None = None,
    verifier: Verifier | None = None,
):
    database = Database(database_path)
    await database.connect()
    task_store = TaskStore(database)
    performance = ModelPerformanceStore(database)
    event_bus = EventBus()
    registry = ModelRegistry(models or [local_model()])
    provider_registry = ProviderRegistry(providers or [DeterministicProvider()])
    health = ProviderHealth()
    usage = UsageTracker()
    router = ModelRouter(registry, provider_registry, performance, health)
    runtime = TaskRuntime(
        task_store=task_store,
        performance_store=performance,
        event_bus=event_bus,
        model_registry=registry,
        providers=provider_registry,
        model_router=router,
        provider_health=health,
        classifier=TaskClassifier(),
        planner=Planner(3),
        executor=Executor(),
        verifier=verifier or Verifier(),
        permission_engine=PermissionEngine(),
        usage_tracker=usage,
    )
    return SimpleNamespace(
        database=database,
        task_store=task_store,
        performance=performance,
        event_bus=event_bus,
        registry=registry,
        providers=provider_registry,
        health=health,
        router=router,
        runtime=runtime,
    )


async def wait_for_status(
    store: TaskStore,
    task_id: str,
    statuses: set[TaskStatus],
    timeout: float = 2,
) -> Task:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        task = await store.get(task_id)
        if task and task.status in statuses:
            return task
        await asyncio.sleep(0.01)
    task = await store.get(task_id)
    raise AssertionError(f"Task did not reach {statuses}; current={task.status if task else None}")


async def close_harness(harness) -> None:
    for active in tuple(harness.runtime.active.values()):
        active.cancel()
    if harness.runtime.active:
        await asyncio.gather(*harness.runtime.active.values(), return_exceptions=True)
    await harness.database.close()

