from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.autonomous_worker import AutonomousAgentWorker
from app.agents.evaluator import AgentEvaluator
from app.agents.factory import AgentFactory
from app.agents.lifecycle import AgentLifecycle
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.schemas import AgentStatus
from app.capabilities.registry import CapabilityRegistry
from app.execution.evidence_collector import EvidenceCollector
from app.persistence.database import Database
from app.persistence.model_performance_store import ModelPerformanceStore
from app.providers.base import BaseProvider, ProviderRequest, ProviderResponse, ToolCall
from app.providers.deterministic import DeterministicProvider
from app.routing.model_registry import ModelRegistry
from app.routing.model_router import ModelRouter
from app.routing.provider_health import ProviderHealth
from app.schemas.approvals import PermissionLevel
from app.schemas.routing import ModelDefinition
from app.schemas.tasks import Task
from app.skills.executor import SkillExecutor
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry
from app.tools_builtin.filesystem import FilesystemTool
from app.tools_builtin.terminal import TerminalTool


class ScriptedToolCallingProvider(BaseProvider):
    """A REAL provider implementation (not a bare mock of the worker) that
    speaks the same generate_with_tools contract the Google provider does,
    replaying a scripted sequence of ProviderResponse objects. This lets
    the autonomous loop be exercised end-to-end - real ToolExecutor, real
    FilesystemTool - without a network call to an LLM."""

    name = "scripted"

    def __init__(self, responses: list[ProviderResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    @property
    def supports_tool_calls(self) -> bool:
        return True

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    async def generate_with_tools(self, request, tools, history=None):
        if self.calls >= len(self._responses):
            # Exhausted script: always terminate on further calls so a
            # test bug never hangs the loop.
            return ProviderResponse(text="No further scripted action.")
        response = self._responses[self.calls]
        self.calls += 1
        return response


def model_definition() -> ModelDefinition:
    return ModelDefinition(
        provider="scripted", model_id="scripted-v1", enabled=True,
        capabilities={"general", "planning", "structured_output"},
        quality_tier="balanced", speed_tier="fast", cost_tier="low",
        supports_tools=True, priority=100,
    )


async def build_worker(tmp_path: Path, responses: list[ProviderResponse], *, max_steps: int = 8):
    from app.providers.base import ProviderRegistry

    database = Database(tmp_path / "perf.db")
    await database.connect()
    performance = ModelPerformanceStore(database)
    registry = ModelRegistry([model_definition()])
    scripted = ScriptedToolCallingProvider(responses)
    providers = ProviderRegistry([scripted])
    health = ProviderHealth()
    router = ModelRouter(registry, providers, performance, health)

    tools = ToolRegistry()
    tools.register(FilesystemTool())
    tools.register(TerminalTool())
    executor_ = __import__("app.tools.executor", fromlist=["ToolExecutor"]).ToolExecutor(
        tools, EvidenceCollector(tmp_path / "audit.jsonl")
    )
    worker = AutonomousAgentWorker(
        tool_registry=tools, tool_executor=executor_, model_router=router, providers=providers,
        max_steps=max_steps, max_runtime_seconds=30, provider_health=health,
    )
    return SimpleNamespace(worker=worker, database=database, scripted=scripted, tools=tools)


@pytest.mark.asyncio
async def test_autonomous_worker_runs_real_multi_step_tool_loop(tmp_path: Path):
    """The agent itself decides two DIFFERENT real tool calls in sequence
    (list a directory, then read a file it just observed) rather than
    running one pre-picked skill, using the real FilesystemTool through
    the real ToolExecutor."""
    target = tmp_path / "notes.txt"
    target.write_text("hello from the workspace", encoding="utf-8")

    responses = [
        ProviderResponse(text="", tool_calls=[
            ToolCall(name="filesystem", arguments={"action": "list", "path": str(tmp_path)}),
        ]),
        ProviderResponse(text="", tool_calls=[
            ToolCall(name="filesystem", arguments={"action": "read", "path": str(target)}),
        ]),
        ProviderResponse(text="Found notes.txt and read its contents: hello from the workspace."),
    ]
    harness = await build_worker(tmp_path, responses)
    events = []

    async def emit(event_type, message, payload):
        events.append((event_type, message, payload))

    task = Task(goal="inspect the workspace", user_request="inspect the workspace")
    result = await harness.worker.run(
        "inspect the workspace", task, emit,
        permission_level=PermissionLevel.L1, allowed_roots=(tmp_path.resolve(),),
    )

    assert harness.scripted.calls == 3
    assert result.structured_data["step_count"] == 2
    steps = result.structured_data["steps"]
    assert steps[0]["tool"] == "filesystem" and steps[0]["inputs"]["action"] == "list"
    assert steps[1]["tool"] == "filesystem" and steps[1]["inputs"]["action"] == "read"
    assert all(step["success"] for step in steps)
    assert result.structured_data["verification"]["passed"] is True
    assert "hello from the workspace" in result.response
    assert any(evidence for evidence in result.evidence)
    tool_events = [event for event, _, _ in events if event in {"tool_selected", "tool_started", "tool_completed"}]
    assert "tool_selected" in tool_events and "tool_completed" in tool_events

    await harness.database.close()


@pytest.mark.asyncio
async def test_autonomous_worker_max_steps_cutoff_does_not_hang(tmp_path: Path):
    """A provider that ALWAYS wants another tool call must still be
    stopped by the step bound - this is the bounded-loop guarantee, not
    a single deterministic skill run."""
    responses = [
        ProviderResponse(text="", tool_calls=[
            ToolCall(name="filesystem", arguments={"action": "list", "path": str(tmp_path)}),
        ])
        for _ in range(20)
    ]
    harness = await build_worker(tmp_path, responses, max_steps=3)

    async def emit(event_type, message, payload):
        return None

    task = Task(goal="keep listing forever", user_request="keep listing forever")
    result = await harness.worker.run(
        "keep listing forever", task, emit,
        permission_level=PermissionLevel.L1, allowed_roots=(tmp_path.resolve(),),
    )

    assert harness.scripted.calls == 3
    assert result.structured_data["step_count"] == 3
    assert result.structured_data["hit_step_bound"] is True
    assert "3-step bound" in result.response

    await harness.database.close()


@pytest.mark.asyncio
async def test_autonomous_worker_reports_tool_failure_honestly(tmp_path: Path):
    """A tool call against a path outside allowed_roots must fail for a
    REAL reason (path policy), and that failure must show up as evidence,
    not be silently swallowed."""
    responses = [
        ProviderResponse(text="", tool_calls=[
            ToolCall(name="filesystem", arguments={"action": "read", "path": str(tmp_path.parent / "outside.txt")}),
        ]),
        ProviderResponse(text="That path was not accessible; stopping."),
    ]
    harness = await build_worker(tmp_path, responses)

    async def emit(event_type, message, payload):
        return None

    task = Task(goal="read an out-of-bounds file", user_request="read an out-of-bounds file")
    result = await harness.worker.run(
        "read an out-of-bounds file", task, emit,
        permission_level=PermissionLevel.L1, allowed_roots=(tmp_path.resolve(),),
    )

    step = result.structured_data["steps"][0]
    assert step["success"] is False
    assert result.structured_data["verification"]["passed"] is False

    await harness.database.close()


def tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FilesystemTool())
    registry.register(TerminalTool())
    return registry


@pytest.mark.asyncio
async def test_agent_factory_creates_autonomous_agent_with_no_bound_skill(tmp_path: Path):
    """'create a researcher agent for X' must synthesize a working agent
    on the fly - no human pre-registered skill required."""
    tools = tool_registry()
    capabilities = await CapabilityRegistry.from_tools(tools)
    skills = SkillRegistry(tmp_path / "skills")
    agents = AgentRegistry(tmp_path / "agents")
    factory = AgentFactory(agents, AgentEvaluator(capabilities, skills, tools))

    agent, validation, created = factory.create_autonomous(
        "Filesystem Researcher Agent",
        "Investigates the local filesystem",
        "List and summarise what is inside the workspace directory",
        tools=["filesystem", "terminal"],
    )

    assert created
    assert agent.skills == []  # no bound skill: this IS the free-form marker
    assert agent.status == AgentStatus.READY
    assert validation.passed

    # Calling again with the same name finds the existing agent instead of
    # creating a duplicate.
    again, _, created_again = factory.create_autonomous(
        "Filesystem Researcher Agent", "Investigates the local filesystem", "different goal text",
    )
    assert created_again is False
    assert again.id == agent.id


@pytest.mark.asyncio
async def test_agent_runtime_delegates_to_autonomous_worker_for_skill_less_agent(tmp_path: Path):
    """AgentRuntime.delegate must run the free-form autonomous loop when
    the agent has no bound skill, while a skill-bound agent keeps using
    the existing SkillExecutor path unchanged."""
    target = tmp_path / "readme.txt"
    target.write_text("VYOM autonomous agent test fixture", encoding="utf-8")

    responses = [
        ProviderResponse(text="", tool_calls=[
            ToolCall(name="filesystem", arguments={"action": "read", "path": str(target)}),
        ]),
        ProviderResponse(text="Read readme.txt: VYOM autonomous agent test fixture."),
    ]
    harness = await build_worker(tmp_path, responses)

    skills = SkillRegistry(tmp_path / "skills")
    agents = AgentRegistry(tmp_path / "agents")
    agents.register(
        __import__("app.agents.schemas", fromlist=["AgentSpec"]).AgentSpec(
            id="freeform-agent", name="Freeform Agent", role="Researcher", description="test",
            goals=["investigate"], capabilities=["result.verify"], skills=[], tools=["filesystem"],
            status=AgentStatus.READY,
        )
    )
    runtime = AgentRuntime(agents, AgentLifecycle(agents), SkillExecutor(skills, action_engine=None), harness.worker)

    events = []

    async def emit(kind, message, payload):
        events.append(kind)

    parent = Task(goal="investigate the workspace", user_request="investigate the workspace")
    result, mission = await runtime.delegate(
        parent, "freeform-agent", "read readme.txt and report its contents", emit,
        allowed_roots=(tmp_path.resolve(),),
    )

    assert mission.status == "completed"
    assert "readme.txt" in result.response or "VYOM autonomous agent test fixture" in result.response
    assert agents.get("freeform-agent").performance.successes == 1
    assert "agent_started" in events and "agent_completed" in events

    await harness.database.close()


@pytest.mark.asyncio
async def test_agent_runtime_still_runs_bound_skill_unchanged(tmp_path: Path):
    """Regression guard: an agent WITH a bound skill must not be routed
    through the autonomous worker - existing behaviour is untouched."""
    from app.execution.action_engine import ActionEngine

    class SuccessfulActionEngine:
        def supports(self, intent: str) -> bool:
            return True

        async def execute(self, task, profile, emit):
            from app.schemas.results import ExecutionResult
            from app.schemas.routing import UsageRecord

            await emit("test_passed", "Build passed.", {})
            return ExecutionResult(
                response="Build passed.",
                structured_data={"verification": {"passed": True}},
                evidence=["exit code 0"],
                usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )

    skills = SkillRegistry(tmp_path / "skills")
    from app.skills.schemas import SkillSpec, SkillStatus, SkillStep, SkillVerification

    skill = SkillSpec(
        id="project-build-check",
        name="Project Build Check",
        version="1.0.0",
        description="Check whether a project builds correctly",
        category="coding",
        required_capabilities=["filesystem.read", "terminal.execute", "coding.build_check", "coding.verify"],
        required_tools=["filesystem", "terminal"],
        required_permissions=PermissionLevel.L1,
        steps=[SkillStep(id="inspect", action="inspect_project", capability="filesystem.read")],
        verification=SkillVerification(checks=["real exit code"]),
        created_by="autonomous-agent-test",
        status=SkillStatus.ACTIVE,
    )
    skills.register(skill, instructions="x", changelog="x")
    agents = AgentRegistry(tmp_path / "agents")
    from app.agents.schemas import AgentSpec

    agents.register(AgentSpec(
        id="bound-agent", name="Bound", role="Builder", description="test", goals=["build"],
        capabilities=["coding.build_check"], skills=["project-build-check"], status=AgentStatus.READY,
    ))
    runtime = AgentRuntime(
        agents, AgentLifecycle(agents), SkillExecutor(skills, SuccessfulActionEngine()), autonomous_worker=None,
    )

    async def emit(kind, message, payload):
        return None

    parent = Task(goal="build", user_request="build")
    result, mission = await runtime.delegate(parent, "bound-agent", "build", emit)
    assert result.response == "Build passed." and mission.status == "completed"
