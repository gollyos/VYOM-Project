from __future__ import annotations

from pathlib import Path

import pytest

from app.adaptive import AdaptiveLearner, ExperienceStore, StrategyEngine, fingerprint
from app.adaptive.auto_promotion import SkillAutoPromoter, skill_id_for
from app.adaptive.learned_router import LearnedRouter
from app.adaptive.learner import AdaptiveLearningBridge
from app.adaptive.schemas import Experience
from app.learning.improvement_engine import ImprovementEngine
from app.memory.embeddings import LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryQuery, MemoryType
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.persistence.model_performance_store import ModelPerformanceStore
from app.providers.deterministic import DeterministicProvider
from app.providers.base import ProviderRegistry
from app.routing.model_registry import ModelRegistry
from app.routing.model_router import ModelRouter
from app.routing.provider_health import ProviderHealth
from app.runtime.event_bus import EventBus
from app.schemas.approvals import PermissionLevel
from app.schemas.events import BrainEvent, EventType
from app.schemas.results import ExecutionResult, VerificationResult
from app.schemas.routing import UsageRecord
from app.schemas.tasks import Task, TaskDomain, TaskProfile, TaskStatus
from app.skills.registry import SkillRegistry
from app.skills.sandbox import SkillSandbox
from app.skills.teachable import TeachableSkillService
from app.tools.registry import ToolRegistry
from app.tools_builtin import FilesystemTool, GitTool, TerminalTool

from .helpers import local_model


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "loop.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def adaptive_stack(database):
    store = ExperienceStore(database)
    strategies = StrategyEngine(database)
    learner = AdaptiveLearner(store, strategies)
    learned_router = LearnedRouter(learner, minimum_samples=2)
    return store, strategies, learner, learned_router


def tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FilesystemTool())
    registry.register(TerminalTool())
    registry.register(GitTool())
    return registry


async def memory_stack(database: Database) -> MemoryManager:
    store = MemoryStore(database)
    return MemoryManager(store, MemoryRetriever(store, LocalHashEmbeddingProvider()))


# ---------------------------------------------------------------------------
# (a) Router-bias test: a learned negative bias measurably changes which
#     model the SAME ModelRouter picks for an identical task.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learned_router_bias_changes_model_selection(database, adaptive_stack):
    _store, _strategies, learner, learned_router = adaptive_stack
    performance_store = ModelPerformanceStore(database)

    model_a = local_model(provider="a", model_id="model-a", priority=100)
    model_b = local_model(provider="b", model_id="model-b", priority=100)
    registry = ModelRegistry([model_a, model_b])
    providers = ProviderRegistry([DeterministicProvider(), DeterministicProvider()])
    providers.providers["a"] = DeterministicProvider()
    providers.providers["a"].name = "a"
    providers.providers["b"] = DeterministicProvider()
    providers.providers["b"].name = "b"
    health = ProviderHealth()
    router = ModelRouter(registry, providers, performance_store, health)

    task = Task(goal="Extract site content", user_request="Extract the article text")
    profile = TaskProfile(domain=TaskDomain.RESEARCH, complexity=1, needs=set())

    # BASELINE: with no history and identical model definitions, the two
    # models tie and the router's stable ordering picks model-a first.
    baseline = await router.route(task, profile)
    assert baseline.primary_model == "model-a"

    # Real failure evidence for model-a in the SAME domain, via the SAME
    # mechanism a genuine task failure produces: TaskRuntime._finish_result
    # calls performance_store.record() after every task; here we call it
    # directly with success=False, exactly like a failed task would.
    for _ in range(2):
        failed_task = Task(
            goal="Extract site content", user_request="Extract the article text",
            domain=TaskDomain.RESEARCH, assigned_model="model-a",
        )
        failed_task.result = ExecutionResult(response="", usage=UsageRecord(total_tokens=0, estimated_cost=0))
        failed_task.verification = VerificationResult(passed=False, score=0.0, summary="failed")
        await performance_store.record(
            task=failed_task, model="model-a", provider="a", success=False,
            latency_ms=50.0, retries=0, fallback_used=False,
        )

    # Only 2 samples: below ModelRouter's own direct-statistics threshold
    # (requires samples >= 3), so this isolates the LEARNED ROUTER layer's
    # own effect rather than the pre-existing statistics path.
    stats = await performance_store.statistics("model-a", "research")
    assert stats["samples"] == 2

    # Attach the learned router — this is exactly the wiring gap: without
    # this line the router never looks at adaptive evidence at all.
    router.learned_router = learned_router

    biased = await router.route(task, profile)
    assert biased.primary_model == "model-b", (
        f"expected the learned router's negative bias for model-a in research "
        f"(2 recorded failures) to flip routing to model-b; got {biased.primary_model} "
        f"reason={biased.reason_selected}"
    )
    assert "learned:" in biased.reason_selected


# ---------------------------------------------------------------------------
# (b) Skill auto-promotion test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_tool_sequence_auto_promotes_a_taught_skill(database, tmp_path):
    store = ExperienceStore(database)
    skill_registry = SkillRegistry(tmp_path / "skills")
    tools = tool_registry()
    teachable = TeachableSkillService(skill_registry, tools)
    promoter = SkillAutoPromoter(store, teachable, min_repetitions=3)

    # Below the threshold: two successful runs of the same pattern must NOT
    # promote a skill yet.
    for _ in range(2):
        await store.record(Experience(
            task_type="fs_search", domain="coding", success=True, verification_score=0.9,
            task_fingerprint=fingerprint("search the repository for TODO"),
            tools_used=["filesystem"],
        ))
    assert await promoter.consider(task_type="fs_search", domain="coding", tools_used=["filesystem"]) is None
    assert skill_registry.get(skill_id_for("fs_search", ("filesystem",))) is None

    # The third success crosses min_repetitions=3 — a real SkillSpec must
    # now exist, registered by the EXISTING TeachableSkillService, not a
    # log line.
    await store.record(Experience(
        task_type="fs_search", domain="coding", success=True, verification_score=0.9,
        task_fingerprint=fingerprint("search the repository for TODO"),
        tools_used=["filesystem"],
    ))
    skill = await promoter.consider(task_type="fs_search", domain="coding", tools_used=["filesystem"])
    assert skill is not None
    assert skill.id == skill_id_for("fs_search", ("filesystem",))
    assert skill.category == "auto-taught"
    from app.skills.schemas import SkillStatus
    assert skill.status == SkillStatus.TESTING  # never auto-activated

    persisted = skill_registry.get(skill.id)
    assert persisted is not None
    assert persisted.required_tools == ["filesystem"]

    # Calling again must not create a duplicate/second version.
    again = await promoter.consider(task_type="fs_search", domain="coding", tools_used=["filesystem"])
    assert again is None


@pytest.mark.asyncio
async def test_auto_promotion_flows_through_the_event_bus(database, tmp_path):
    """End-to-end: a real TASK_COMPLETED event, published on the SAME
    EventBus every task completion uses, drives AdaptiveLearningBridge to
    record an Experience AND (once the pattern repeats enough) to emit a
    real SKILL_CREATED event from a real persisted skill."""
    from app.persistence.task_store import TaskStore

    task_store = TaskStore(database)
    store = ExperienceStore(database)
    strategies = StrategyEngine(database)
    learner = AdaptiveLearner(store, strategies)
    skill_registry = SkillRegistry(tmp_path / "skills2")
    teachable = TeachableSkillService(skill_registry, tool_registry())
    promoter = SkillAutoPromoter(store, teachable, min_repetitions=2)
    event_bus = EventBus()
    bridge = AdaptiveLearningBridge(event_bus, learner, task_store, auto_promoter=promoter)
    bridge.start()
    try:
        skill_created = []
        subscriber = event_bus.subscribe()

        import asyncio

        async def _watch():
            async for event in subscriber:
                if event.type == EventType.SKILL_CREATED:
                    skill_created.append(event)
                    return

        watcher = asyncio.create_task(_watch())

        for index in range(2):
            task = Task(
                goal="List repository files", user_request="list the files in my project",
                domain=TaskDomain.CODING,
            )
            task.status = TaskStatus.COMPLETED
            task.profile = TaskProfile(domain=TaskDomain.CODING, complexity=1, intent="fs_list", needs={"tools"})
            task.metadata["tools_used"] = ["filesystem"]
            task.result = ExecutionResult(response="listed", usage=UsageRecord(total_tokens=0, estimated_cost=0))
            task.verification = VerificationResult(passed=True, score=0.9, summary="ok")
            await task_store.save(task)
            await event_bus.publish(BrainEvent(
                task_id=task.id, type=EventType.TASK_COMPLETED,
                human_readable_message="done", structured_payload={},
            ))

        await asyncio.wait_for(watcher, timeout=2.0)
        assert len(skill_created) == 1
        payload = skill_created[0].structured_payload
        assert payload["skill_id"] == skill_id_for("fs_list", ("filesystem",))
        assert skill_registry.get(payload["skill_id"]) is not None
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# (c) Lesson persists and is recallable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lesson_persists_and_is_recallable(database):
    memory_manager = await memory_stack(database)
    engine = ImprovementEngine(memory_manager)

    learned = await engine.record_failure(
        task_id="task-1", title="Build failed",
        error_summary="Cannot find module react — dependency missing",
        project_id="vyom",
    )
    assert learned is not None
    failure, lesson = learned
    assert lesson.type == MemoryType.LESSON

    results = await memory_manager.search(MemoryQuery(text="", types={MemoryType.LESSON}, limit=10))
    assert any(item.memory.id == lesson.id for item in results)

    relevant = await engine.relevant_lessons("install declared project dependencies", project_id="vyom")
    assert any(item.memory.id == lesson.id for item in relevant)


@pytest.mark.asyncio
async def test_adaptive_router_bias_api_reports_live_state(database, adaptive_stack, tmp_path):
    """The GET /api/adaptive/router-bias contract: read learned_router.learner
    the same way the endpoint does, and confirm it reflects a real recorded
    failure — proving the endpoint would not be reporting a stale/fake view."""
    from app.api.adaptive import router_bias as router_bias_endpoint
    from types import SimpleNamespace

    _store, _strategies, learner, learned_router = adaptive_stack
    performance_store = ModelPerformanceStore(database)

    for _ in range(2):
        failed_task = Task(
            goal="g", user_request="g", domain=TaskDomain.RESEARCH, assigned_model="model-a",
        )
        failed_task.result = ExecutionResult(response="", usage=UsageRecord(total_tokens=0, estimated_cost=0))
        failed_task.verification = VerificationResult(passed=False, score=0.0, summary="failed")
        await performance_store.record(
            task=failed_task, model="model-a", provider="a", success=False,
            latency_ms=10.0, retries=0, fallback_used=False,
        )

    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(learned_router=learned_router)))
    payload = await router_bias_endpoint(fake_request, domain="research")
    assert payload["attached"] is True
    assert "model-a" in payload["models"]
    assert "research" in payload["models"]["model-a"]["domain_bias"]
    assert payload["models"]["model-a"]["domain_bias"]["research"]["bias"] < 0
