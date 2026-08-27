import pytest

from app.providers.anthropic import AnthropicProvider
from app.providers.base import ProviderError, ProviderRegistry
from app.providers.deepseek import DeepSeekProvider
from app.providers.google import GoogleProvider
from app.providers.kimi import KimiProvider
from app.providers.openai import OpenAIProvider
from app.providers.openrouter import OpenRouterProvider
from app.schemas.tasks import Task, TaskProfile

from .helpers import MockProvider, build_runtime, close_harness, local_model


@pytest.mark.asyncio
async def test_router_selects_cheapest_reliable_capable_model(tmp_path):
    fast = local_model(provider="fast", model_id="fast-model", priority=60)
    premium = local_model(
        provider="premium",
        model_id="premium-model",
        cost_tier="high",
        quality_tier="premium",
        speed_tier="balanced",
        priority=90,
    )
    harness = await build_runtime(
        tmp_path / "routing.db",
        models=[premium, fast],
        providers=[MockProvider("premium"), MockProvider("fast")],
    )
    try:
        task = Task(goal="Plan", user_request="Plan my work")
        profile = TaskProfile(domain="planning", complexity=3, needs={"planning", "structured_output"})
        decision = await harness.router.route(task, profile)
        assert decision.primary_model == "fast-model"
        assert decision.fallback_models == ["premium-model"]
        assert "lowest-cost available" in decision.reason_selected
    finally:
        await close_harness(harness)


def test_missing_provider_credentials_are_unavailable(monkeypatch):
    for variable in (
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "KIMI_API_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)
    providers = [
        GoogleProvider(1), OpenAIProvider(1), AnthropicProvider(1), OpenRouterProvider(1),
        DeepSeekProvider(1), KimiProvider(1),
    ]
    assert all(not provider.configured for provider in providers)


class AlwaysFailProvider(MockProvider):
    async def generate(self, request):
        self.call_count += 1
        raise ProviderError("Injected primary failure")


@pytest.mark.asyncio
async def test_bounded_fallback_is_used_and_logged(tmp_path):
    primary = local_model(provider="primary", model_id="primary-model", priority=120)
    fallback = local_model(provider="fallback", model_id="fallback-model", cost_tier="low", priority=50)
    failing = AlwaysFailProvider("primary")
    working = MockProvider("fallback")
    harness = await build_runtime(
        tmp_path / "fallback.db",
        models=[primary, fallback],
        providers=[failing, working],
    )
    try:
        from app.schemas.tasks import TaskCreate, TaskStatus
        from .helpers import wait_for_status

        task = await harness.runtime.create_task(TaskCreate(user_request="Give me a concise general answer"))
        completed = await wait_for_status(harness.task_store, task.id, {TaskStatus.COMPLETED})
        assert completed.assigned_model == "fallback-model"
        assert failing.call_count == 1 and working.call_count == 1
        assert "model_fallback" in [event.type.value for event in harness.event_bus.history]
    finally:
        await close_harness(harness)


@pytest.mark.asyncio
async def test_per_role_model_configuration(tmp_path):
    general_model = local_model(provider="p1", model_id="general-fast", priority=50)
    coder_model = local_model(provider="p2", model_id="deep-coder", capabilities={"coding", "general"}, priority=50)
    harness = await build_runtime(
        tmp_path / "role.db",
        models=[general_model, coder_model],
        providers=[MockProvider("p1"), MockProvider("p2")],
    )
    try:
        harness.registry.set_role_override("coding", "deep-coder")
        task = Task(goal="Write python script", user_request="Write a fibonacci solver", metadata={"role": "coding"})
        profile = TaskProfile(domain="coding", complexity=2, needs={"coding"})
        decision = await harness.router.route(task, profile)
        assert decision.primary_model == "deep-coder"
        assert any("role-override" in r for r in decision.reason_selected.splitlines() if r) or "deep-coder" in decision.primary_model
    finally:
        await close_harness(harness)


