from __future__ import annotations

from app.capabilities.registry import CapabilityRegistry
from app.schemas.approvals import PermissionLevel
from app.tools.registry import ToolRegistry

from .schemas import SkillEvaluation, SkillSpec


class SkillSandbox:
    def __init__(self, capabilities: CapabilityRegistry, tools: ToolRegistry):
        self.capabilities = capabilities
        self.tools = tools

    async def test(self, skill: SkillSpec) -> SkillEvaluation:
        tool_names = {tool.metadata.name for tool in self.tools.list()}
        checks = {
            "capabilities_available": self.capabilities.supports(skill.required_capabilities),
            "tools_registered": all(tool in tool_names for tool in skill.required_tools),
            "bounded_runtime": skill.budget.max_runtime_seconds <= 300,
            "bounded_calls": skill.budget.max_tool_calls <= 20 and skill.budget.max_model_calls <= 3,
            "safe_auto_permission": skill.required_permissions in {PermissionLevel.L0, PermissionLevel.L1},
            "verification_defined": bool(skill.verification.checks),
            "steps_within_budget": len(skill.steps) <= skill.budget.max_tool_calls,
        }
        score = sum(checks.values()) / len(checks)
        errors = [name for name, passed in checks.items() if not passed]
        return SkillEvaluation(
            passed=all(checks.values()),
            score=score,
            checks=checks,
            evidence=[f"Sandbox policy check: {name}={passed}" for name, passed in checks.items()],
            errors=errors,
        )
