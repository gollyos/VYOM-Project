from __future__ import annotations

from app.schemas.approvals import PermissionLevel

from .evaluator import AgentEvaluator
from .registry import AgentRegistry
from .schemas import AgentBudget, AgentMemoryScope, AgentModelPolicy, AgentSpec, AgentStatus, AgentValidation


class AgentFactory:
    def __init__(self, registry: AgentRegistry, evaluator: AgentEvaluator):
        self.registry = registry
        self.evaluator = evaluator

    def create_project_health(self) -> tuple[AgentSpec, AgentValidation, bool]:
        existing = self.registry.find_equivalent("Project Health Agent", "project build test git health")
        if existing:
            return existing, self.evaluator.validate(existing), False
        agent = AgentSpec(
            id="project-health-agent",
            name="Project Health Agent",
            role="Repository health verifier",
            description="Inspects repository structure and Git state, runs available build checks, reports risks, and requires evidence.",
            goals=["Assess project health", "Run safe build verification", "Report evidence and risks"],
            capabilities=["filesystem.read", "git.diff", "coding.build_check", "coding.verify"],
            skills=["project-build-check"],
            tools=["filesystem", "git", "terminal"],
            model_policy=AgentModelPolicy(preferred_capabilities=["coding"], quality_floor="basic", cost_priority="high"),
            memory_scope=[AgentMemoryScope.TASK, AgentMemoryScope.PROJECT],
            permissions=PermissionLevel.L1,
            budget=AgentBudget(max_depth=1, max_parallel_agents=1, max_model_calls=0, max_tool_calls=12, max_runtime_seconds=300, max_cost=0),
            verification_policy=["build/test exit codes must be real", "require tool evidence", "never fabricate unavailable checks"],
            status=AgentStatus.TESTING,
        )
        validation = self.evaluator.validate(agent)
        agent.status = AgentStatus.TESTING if validation.passed else AgentStatus.FAILED
        self.registry.register(agent)
        return agent, validation, True
