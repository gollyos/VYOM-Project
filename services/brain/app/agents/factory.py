from __future__ import annotations

import re

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

    def create_autonomous(
        self,
        name: str,
        role: str,
        goal: str,
        *,
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
        permissions: PermissionLevel = PermissionLevel.L1,
        max_tool_calls: int = 8,
        max_runtime_seconds: int = 180,
    ) -> tuple[AgentSpec, AgentValidation, bool]:
        """Synthesize a NEW agent on the fly from a free-form goal, with no
        bound skill. AgentRuntime.delegate then runs it through the
        autonomous ReAct worker instead of a pre-registered skill - this
        is how 'create a researcher agent for X' becomes a working agent
        without a human having authored a skill for X in advance.

        `id` is derived deterministically from `name` so a repeated
        request for the same agent finds the existing one instead of
        piling up near-duplicates (mirrors find_equivalent's intent)."""
        existing = self.registry.find_equivalent(name, role)
        if existing:
            return existing, self.evaluator.validate(existing), False
        slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:48] or "autonomous-agent"
        agent_id = slug if len(slug) >= 3 else f"agent-{slug}"
        # Capabilities default to whatever tools this agent is allowed to
        # use, expressed as the SAME '<tool>.execute' ids CapabilityRegistry
        # derives from the live tool registry - so a freshly synthesized
        # agent validates against capabilities that are ACTUALLY
        # registered, rather than an unrelated placeholder capability no
        # tool provides.
        resolved_tools = tools or []
        resolved_capabilities = capabilities or [f"{tool}.execute" for tool in resolved_tools] or ["result.verify"]
        agent = AgentSpec(
            id=agent_id,
            name=name,
            role=role,
            description=f"Autonomous agent: {goal}",
            goals=[goal],
            capabilities=resolved_capabilities,
            skills=[],  # No bound skill: this is the free-form mode marker.
            tools=resolved_tools,
            model_policy=AgentModelPolicy(preferred_capabilities=["general"], quality_floor="basic", cost_priority="normal"),
            memory_scope=[AgentMemoryScope.TASK],
            permissions=permissions,
            budget=AgentBudget(
                max_depth=1, max_parallel_agents=1, max_model_calls=max_tool_calls,
                max_tool_calls=max_tool_calls, max_runtime_seconds=max_runtime_seconds, max_cost=0.05,
            ),
            verification_policy=["require evidence", "never fabricate unavailable tool results"],
            status=AgentStatus.READY,
        )
        validation = self.evaluator.validate(agent)
        # An autonomous agent has no skill to validate against - the
        # 'skills_active' check is vacuously true (empty list) so a real
        # tool/capability mismatch is still what decides pass/fail here.
        agent.status = AgentStatus.READY if validation.passed else AgentStatus.FAILED
        self.registry.register(agent)
        return agent, validation, True
