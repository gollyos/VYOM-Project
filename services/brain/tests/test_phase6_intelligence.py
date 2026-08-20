from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.capability_matcher import AgentCapabilityMatcher
from app.agents.evaluator import AgentEvaluator
from app.agents.factory import AgentFactory
from app.agents.lifecycle import AgentLifecycle
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.schemas import AgentBudget, AgentMemoryScope, AgentSpec, AgentStatus
from app.capabilities.discovery import CapabilityDiscovery
from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import CapabilityRecord, CapabilitySource
from app.learning.failure_analyzer import FailureAnalyzer
from app.learning.improvement_engine import ImprovementEngine
from app.learning.intelligence_engine import IntelligenceEngine
from app.memory.embeddings import DisabledEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryQuery,
    MemoryType,
    ProvenanceType,
    RelationType,
    Sensitivity,
    VerificationState,
)
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.runtime.task_classifier import TaskClassifier
from app.schemas.approvals import PermissionLevel
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskDomain, TaskProfile
from app.skills.builder import SkillBuilder
from app.skills.evaluator import SkillEvaluator
from app.skills.executor import SkillExecutor
from app.skills.matcher import SkillMatcher
from app.skills.registry import DuplicateSkillError, SkillRegistry
from app.skills.sandbox import SkillSandbox
from app.skills.schemas import SkillSpec, SkillStatus, SkillStep, SkillVerification
from app.skills.versioning import SkillVersioning
from app.tools.registry import ToolRegistry
from app.tools_builtin import FilesystemTool, GitTool, TerminalTool


def provenance(kind: ProvenanceType = ProvenanceType.USER_STATEMENT) -> list[MemoryProvenance]:
    return [MemoryProvenance(type=kind, reference="phase6 test evidence")]


def memory_entry(
    title: str,
    content: str,
    *,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    project_id: str | None = None,
    verification: VerificationState = VerificationState.VERIFIED,
) -> MemoryEntry:
    return MemoryEntry(
        type=memory_type,
        title=title,
        content=content,
        summary=content,
        provenance=provenance(),
        sensitivity=sensitivity,
        project_id=project_id,
        confidence=0.9,
        importance=0.8,
        verification_state=verification,
    )


async def memory_stack(path: Path, embeddings=None):
    database = Database(path)
    await database.connect()
    store = MemoryStore(database)
    provider = embeddings or LocalHashEmbeddingProvider()
    manager = MemoryManager(store, MemoryRetriever(store, provider))
    return database, store, manager


def tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FilesystemTool())
    registry.register(TerminalTool())
    registry.register(GitTool())
    return registry


def skill_spec(
    *,
    skill_id: str = "project-build-check",
    version: str = "1.0.0",
    status: SkillStatus = SkillStatus.ACTIVE,
    permission: PermissionLevel = PermissionLevel.L1,
    capabilities: list[str] | None = None,
) -> SkillSpec:
    return SkillSpec(
        id=skill_id,
        name="Project Build Check",
        version=version,
        description="Check whether a project builds correctly",
        category="coding",
        required_capabilities=capabilities or ["filesystem.read", "terminal.execute", "coding.build_check", "coding.verify"],
        required_tools=["filesystem", "terminal"],
        required_permissions=permission,
        steps=[SkillStep(id="inspect", action="inspect_project", capability="filesystem.read")],
        verification=SkillVerification(checks=["real exit code"]),
        created_by="phase6-test",
        status=status,
        success_rate=0.9,
    )


class SuccessfulActionEngine:
    async def execute(self, task, profile, emit):
        await emit("test_passed", "Mocked bounded action verified", {"exit_code": 0})
        return ExecutionResult(
            response="Build passed.",
            structured_data={"verification": {"passed": True}},
            evidence=["exit code 0"],
        )


@pytest.mark.asyncio
async def test_memory_persists_after_database_restart(tmp_path: Path):
    path = tmp_path / "memory.db"
    database, _, manager = await memory_stack(path)
    saved = await manager.remember(memory_entry("Meeting preference", "Important client meetings after 11 AM", memory_type=MemoryType.PREFERENCE))
    await database.close()
    database, store, _ = await memory_stack(path)
    assert (await store.get(saved.id, touch=False)).content.endswith("11 AM")
    await database.close()


@pytest.mark.asyncio
async def test_hybrid_semantic_and_structured_retrieval(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    await manager.remember(memory_entry("VYOM build", "The repository compiles with npm run build", project_id="vyom"))
    await manager.remember(memory_entry("Other project", "A client meeting is tomorrow", project_id="other"))
    results = await manager.search(MemoryQuery(text="How does the codebase compile?", project_id="vyom"))
    assert results and results[0].memory.title == "VYOM build"
    assert "semantic similarity" in results[0].reasons
    await database.close()


@pytest.mark.asyncio
async def test_memory_provenance_is_inspectable(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    saved = await manager.remember(memory_entry("Verified fact", "Build passed", verification=VerificationState.VERIFIED))
    inspected = await manager.inspect(saved.id)
    assert inspected["provenance"][0]["type"] == "user_statement"
    assert inspected["provenance"][0]["reference"] == "phase6 test evidence"
    await database.close()


@pytest.mark.asyncio
async def test_memory_correction_supersedes_old_fact(tmp_path: Path):
    database, store, manager = await memory_stack(tmp_path / "memory.db")
    old = await manager.remember(memory_entry("Preference", "Morning meetings", memory_type=MemoryType.PREFERENCE))
    new = await manager.correct(old.id, memory_entry("Preference", "Evening meetings", memory_type=MemoryType.PREFERENCE))
    assert (await store.get(old.id, touch=False)).verification_state == VerificationState.SUPERSEDED
    assert new.supersedes == old.id
    assert [item.memory.id for item in await manager.search(MemoryQuery(types={MemoryType.PREFERENCE}))] == [new.id]
    await database.close()


@pytest.mark.asyncio
async def test_memory_forget_hard_deletes_content_and_relations(tmp_path: Path):
    database, store, manager = await memory_stack(tmp_path / "memory.db")
    first = await manager.remember(memory_entry("First", "Forget this"))
    second = await manager.remember(memory_entry("Second", "Keep this"))
    await manager.relationships.connect(first.id, second.id, RelationType.RELATED_TO)
    assert await manager.forget(first.id)
    assert await store.get(first.id, touch=False) is None
    assert await store.relationships(second.id) == []
    await database.close()


@pytest.mark.asyncio
async def test_sensitivity_filter_excludes_highly_sensitive_memory(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    await manager.remember(memory_entry("Private", "Sensitive source context", sensitivity=Sensitivity.HIGHLY_SENSITIVE))
    await manager.remember(memory_entry("Public", "Normal project context"))
    results = await manager.search(MemoryQuery(max_sensitivity=Sensitivity.SENSITIVE))
    assert {item.memory.title for item in results} == {"Public"}
    await database.close()


@pytest.mark.asyncio
async def test_disabled_embeddings_fall_back_to_keyword_retrieval(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db", DisabledEmbeddingProvider())
    await manager.remember(memory_entry("Build command", "npm run build compiles VYOM"))
    results = await manager.search(MemoryQuery(text="build command"))
    assert results and "keyword match" in results[0].reasons
    await database.close()


@pytest.mark.asyncio
async def test_relationship_graph_is_bounded_and_queryable(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    values = [await manager.remember(memory_entry(f"Node {index}", f"Knowledge {index}")) for index in range(4)]
    for left, right in zip(values, values[1:]):
        await manager.relationships.connect(left.id, right.id, RelationType.DEPENDS_ON)
    graph = await manager.relationships.graph(values[0].id, depth=99)
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 3
    await database.close()


def test_secret_material_is_rejected_from_normal_memory():
    with pytest.raises(ValidationError):
        memory_entry("Secret", "api_key=do-not-store")


@pytest.mark.asyncio
async def test_capability_registry_discovers_tools_and_aliases():
    registry = await CapabilityRegistry.from_tools(tool_registry())
    assert registry.supports(["filesystem.read", "coding.build_check", "git.diff"])
    assert registry.search("build project")[0].status.value == "available"


def test_capability_discovery_registers_skill_and_agent():
    registry = CapabilityRegistry()
    discovery = CapabilityDiscovery(registry)
    skill = skill_spec()
    agent = AgentSpec(id="sample-agent", name="Sample Agent", role="Verifier", description="Checks work", goals=["verify"], capabilities=["result.verify"], status=AgentStatus.READY)
    assert discovery.from_skill(skill).capability_id == "skill.project-build-check"
    assert discovery.from_agent(agent).capability_id == "agent.sample-agent"


def test_capability_matcher_reports_missing_capabilities():
    registry = CapabilityRegistry()
    registry.register(CapabilityRecord(capability_id="known", name="Known", description="known", source=CapabilitySource.INTEGRATION, source_id="test"))
    assert AgentCapabilityMatcher(registry).missing(["known", "unknown"]) == ["unknown"]


def test_skill_registry_persists_and_loads_structured_files(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(skill_spec(), instructions="Safe bounded steps", changelog="# Changes")
    loaded = SkillRegistry(tmp_path / "skills")
    assert loaded.load() == 1
    assert loaded.get("project-build-check").steps[0].action == "inspect_project"
    assert (tmp_path / "skills" / "project-build-check" / "tests" / "manifest.yaml").exists()


def test_skill_matching_prefers_active_relevant_skill(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(skill_spec(), instructions="x", changelog="x")
    assert SkillMatcher(registry).match("verify whether this project can build")[0].id == "project-build-check"


def test_duplicate_skill_detection_is_semantic(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(skill_spec(), instructions="x", changelog="x")
    duplicate = skill_spec(skill_id="check-build-project")
    with pytest.raises(DuplicateSkillError):
        registry.register(duplicate, instructions="x", changelog="x")


@pytest.mark.asyncio
async def test_skill_sandbox_passes_bounded_safe_skill(tmp_path: Path):
    capabilities = await CapabilityRegistry.from_tools(tool_registry())
    result = await SkillSandbox(capabilities, tool_registry()).test(skill_spec(status=SkillStatus.TESTING))
    assert result.passed and result.score == 1


@pytest.mark.asyncio
async def test_failed_skill_stays_failed_and_does_not_activate(tmp_path: Path):
    capabilities = await CapabilityRegistry.from_tools(tool_registry())
    candidate = skill_spec(status=SkillStatus.TESTING, capabilities=["unknown.capability"])
    evaluation = await SkillSandbox(capabilities, tool_registry()).test(candidate)
    assert not evaluation.passed
    assert SkillEvaluator().apply(candidate, evaluation).status == SkillStatus.FAILED


@pytest.mark.asyncio
async def test_safe_skill_promotes_only_after_sandbox_passes(tmp_path: Path):
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    registry = SkillRegistry(tmp_path / "skills")
    skill, evaluation, created = await SkillBuilder(registry, SkillSandbox(capabilities, tools)).create_build_check()
    assert created and evaluation.passed and skill.status == SkillStatus.ACTIVE


def test_l2_skill_requires_approval_before_promotion():
    candidate = skill_spec(permission=PermissionLevel.L2, status=SkillStatus.TESTING)
    from app.skills.schemas import SkillEvaluation
    evaluation = SkillEvaluation(passed=True, score=1, checks={"safe": True})
    assert SkillEvaluator().apply(candidate, evaluation).status == SkillStatus.TESTING


def test_skill_versioning_supports_rollback(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    first = skill_spec(version="1.0.0")
    registry.register(first, instructions="v1", changelog="v1")
    second = first.model_copy(deep=True, update={"version": "1.1.0", "previous_version": "1.0.0", "description": "Improved build check"})
    registry.register(second, instructions="v2", changelog="v2", allow_update=True)
    rolled_back = SkillVersioning(registry).rollback(first.id, "1.0.0")
    assert rolled_back.version == "1.0.0"


@pytest.mark.asyncio
async def test_agent_factory_creates_declarative_agent(tmp_path: Path):
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    skills = SkillRegistry(tmp_path / "skills")
    skills.register(skill_spec(), instructions="x", changelog="x")
    agents = AgentRegistry(tmp_path / "agents")
    factory = AgentFactory(agents, AgentEvaluator(capabilities, skills, tools))
    agent, validation, created = factory.create_project_health()
    assert created and validation.passed and agent.status == AgentStatus.TESTING
    assert agent.memory_scope == [AgentMemoryScope.TASK, AgentMemoryScope.PROJECT]


@pytest.mark.asyncio
async def test_agent_validation_checks_tools_skills_and_capabilities(tmp_path: Path):
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    skills = SkillRegistry(tmp_path / "skills")
    skills.register(skill_spec(), instructions="x", changelog="x")
    agents = AgentRegistry(tmp_path / "agents")
    agent, validation, _ = AgentFactory(agents, AgentEvaluator(capabilities, skills, tools)).create_project_health()
    assert validation.passed and all(validation.checks.values())
    assert agent.skills == ["project-build-check"]


@pytest.mark.asyncio
async def test_agent_permission_inheritance_cannot_be_weaker_than_skill(tmp_path: Path):
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    skills = SkillRegistry(tmp_path / "skills")
    skills.register(skill_spec(permission=PermissionLevel.L2), instructions="x", changelog="x")
    agent = AgentSpec(id="weak-agent", name="Weak Agent", role="Builder", description="test", goals=["build"], capabilities=["filesystem.read"], skills=["project-build-check"], tools=["filesystem", "terminal"], permissions=PermissionLevel.L1)
    validation = AgentEvaluator(capabilities, skills, tools).validate(agent)
    assert validation.checks["permission_inheritance"] is False


def test_agent_registry_seeds_permanent_agents(tmp_path: Path):
    config = tmp_path / "agents.yaml"
    config.write_text("seeds:\n  - id: vyom-core\n    name: VYOM Core\n    role: Orchestrator\n    capabilities: [task.plan]\n", encoding="utf-8")
    registry = AgentRegistry(tmp_path / "agents")
    assert registry.seed(config) == 1
    assert registry.get("vyom-core").status == AgentStatus.READY


def test_agent_lifecycle_persists_valid_transitions(tmp_path: Path):
    registry = AgentRegistry(tmp_path / "agents")
    registry.register(AgentSpec(id="life-agent", name="Life Agent", role="Verifier", description="test", goals=["verify"], capabilities=["result.verify"], status=AgentStatus.CREATED))
    lifecycle = AgentLifecycle(registry)
    assert lifecycle.transition("life-agent", AgentStatus.TESTING).status == AgentStatus.TESTING
    assert lifecycle.transition("life-agent", AgentStatus.READY).status == AgentStatus.READY
    assert AgentRegistry(tmp_path / "agents").load() == 1


def test_invalid_agent_lifecycle_transition_is_blocked(tmp_path: Path):
    registry = AgentRegistry(tmp_path / "agents")
    registry.register(AgentSpec(id="archived-agent", name="Archived", role="Verifier", description="test", goals=["verify"], capabilities=["result.verify"], status=AgentStatus.ARCHIVED))
    with pytest.raises(ValueError):
        AgentLifecycle(registry).transition("archived-agent", AgentStatus.READY)


def test_agent_budget_schema_blocks_unbounded_delegation():
    with pytest.raises(ValidationError):
        AgentSpec(
            id="unbounded-agent",
            name="Unbounded",
            role="Unsafe",
            description="test",
            goals=["expand"],
            capabilities=["task.delegate"],
            budget=AgentBudget(max_depth=3, max_parallel_agents=4),
        )


@pytest.mark.asyncio
async def test_agent_delegation_depth_limit_is_enforced(tmp_path: Path):
    skills = SkillRegistry(tmp_path / "skills")
    skills.register(skill_spec(), instructions="x", changelog="x")
    agents = AgentRegistry(tmp_path / "agents")
    agents.register(AgentSpec(id="bounded-agent", name="Bounded", role="Builder", description="test", goals=["build"], capabilities=["coding.build_check"], skills=["project-build-check"], status=AgentStatus.READY, budget=AgentBudget(max_depth=1)))
    runtime = AgentRuntime(agents, AgentLifecycle(agents), SkillExecutor(skills, SuccessfulActionEngine()))
    with pytest.raises(RuntimeError, match="depth limit"):
        await runtime.delegate(Task(goal="build", user_request="build"), "bounded-agent", "build", lambda *args: None, depth=2)


@pytest.mark.asyncio
async def test_agent_delegated_mission_completes_and_tracks_performance(tmp_path: Path):
    skills = SkillRegistry(tmp_path / "skills")
    skills.register(skill_spec(), instructions="x", changelog="x")
    agents = AgentRegistry(tmp_path / "agents")
    agents.register(AgentSpec(id="working-agent", name="Working", role="Builder", description="test", goals=["build"], capabilities=["coding.build_check"], skills=["project-build-check"], status=AgentStatus.READY))
    events = []
    async def emit(kind, message, payload): events.append(kind)
    result, mission = await AgentRuntime(agents, AgentLifecycle(agents), SkillExecutor(skills, SuccessfulActionEngine())).delegate(Task(goal="build", user_request="build"), "working-agent", "build", emit)
    assert result.response == "Build passed." and mission.status == "completed"
    assert agents.get("working-agent").performance.successes == 1
    assert events == ["agent_started", "test_passed", "agent_completed"]


def test_failure_analyzer_only_generalizes_known_patterns():
    analyzer = FailureAnalyzer()
    assert "dependencies" in analyzer.analyze("Cannot find module react")["lesson"]
    assert analyzer.analyze("something vague happened") is None


@pytest.mark.asyncio
async def test_failure_learning_stores_failure_lesson_and_relationship(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    learned = await ImprovementEngine(manager).record_failure(task_id="task", title="Build", error_summary="Environment variable is missing", project_id="vyom")
    failure, lesson = learned
    graph = await manager.relationships.graph(lesson.id)
    assert failure.type == MemoryType.FAILURE and lesson.type == MemoryType.LESSON
    assert graph["edges"][0]["relation"] == RelationType.LEARNED_FROM.value
    await database.close()


@pytest.mark.asyncio
async def test_unjustified_failure_does_not_become_a_lesson(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    assert await ImprovementEngine(manager).record_failure(task_id="task", title="Unknown", error_summary="vague") is None
    await database.close()


def test_phase6_commands_classify_without_paid_models():
    classifier = TaskClassifier()
    assert classifier.classify("Remember that I prefer important client meetings after 11 AM.").intent == "remember_preference"
    assert classifier.classify("Create a Project Health Agent.").intent == "create_project_health_agent"
    assert classifier.classify("Run the build-check skill on this project.").deterministic is True


@pytest.mark.asyncio
async def test_memory_command_generates_dynamic_composer_object_and_event(tmp_path: Path):
    database, _, manager = await memory_stack(tmp_path / "memory.db")
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    skills = SkillRegistry(tmp_path / "skills")
    sandbox = SkillSandbox(capabilities, tools)
    agents = AgentRegistry(tmp_path / "agents")
    evaluator = AgentEvaluator(capabilities, skills, tools)
    action = SuccessfulActionEngine()
    engine = IntelligenceEngine(
        memory=manager,
        capabilities=capabilities,
        skill_registry=skills,
        skill_builder=SkillBuilder(skills, sandbox),
        skill_executor=SkillExecutor(skills, action),
        agent_registry=agents,
        agent_factory=AgentFactory(agents, evaluator),
        agent_runtime=AgentRuntime(agents, AgentLifecycle(agents), SkillExecutor(skills, action)),
        action_engine=action,
        improvement=ImprovementEngine(manager),
        project_id="vyom",
    )
    events = []
    async def emit(kind, message, payload): events.append((kind, payload))
    task = Task(goal="remember", user_request="Remember that I prefer important client meetings after 11 AM.")
    result = await engine.execute(task, TaskProfile(domain=TaskDomain.PERSONAL, intent="remember_preference"), emit)
    assert events[0][0] == "memory_created"
    assert result.ui_composition["objects"][0]["type"] == "memory-cluster"
    assert result.usage.total_tokens == 0
    await database.close()
