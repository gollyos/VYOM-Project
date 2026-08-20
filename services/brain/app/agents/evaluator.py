from __future__ import annotations

from app.capabilities.registry import CapabilityRegistry
from app.schemas.approvals import PermissionLevel
from app.skills.registry import SkillRegistry
from app.skills.schemas import SkillStatus
from app.tools.registry import ToolRegistry

from .schemas import AgentSpec, AgentValidation


class AgentEvaluator:
    def __init__(self, capabilities: CapabilityRegistry, skills: SkillRegistry, tools: ToolRegistry):
        self.capabilities = capabilities
        self.skills = skills
        self.tools = tools

    def validate(self, agent: AgentSpec) -> AgentValidation:
        skill_specs = [self.skills.get(skill_id) for skill_id in agent.skills]
        permission_order = {PermissionLevel.L0: 0, PermissionLevel.L1: 1, PermissionLevel.L2: 2, PermissionLevel.L3: 3}
        checks = {
            "capabilities_available": self.capabilities.supports(agent.capabilities),
            "skills_active": all(skill and skill.status in {SkillStatus.APPROVED, SkillStatus.ACTIVE} for skill in skill_specs),
            "tools_registered": all(any(tool.metadata.name == required for tool in self.tools.list()) for required in agent.tools),
            "permission_inheritance": all(
                skill is not None and permission_order[agent.permissions] >= permission_order[skill.required_permissions]
                for skill in skill_specs
            ),
            "budget_bounded": agent.budget.max_depth <= 2 and agent.budget.max_parallel_agents <= 3 and agent.budget.max_tool_calls <= 20,
            "memory_scoped": bool(agent.memory_scope),
            "verification_defined": bool(agent.verification_policy),
        }
        score = sum(checks.values()) / len(checks)
        return AgentValidation(
            passed=all(checks.values()), score=score, checks=checks,
            evidence=[f"Agent validation: {name}={passed}" for name, passed in checks.items()],
        )
