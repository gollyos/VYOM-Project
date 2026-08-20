from __future__ import annotations

from app.schemas.approvals import PermissionLevel

from .evaluator import SkillEvaluator
from .registry import SkillRegistry
from .sandbox import SkillSandbox
from .schemas import SkillSpec, SkillStatus, SkillStep, SkillVerification


class SkillBuilder:
    def __init__(self, registry: SkillRegistry, sandbox: SkillSandbox):
        self.registry = registry
        self.sandbox = sandbox
        self.evaluator = SkillEvaluator()

    async def create_build_check(self, *, created_by: str = "user-request") -> tuple[SkillSpec, object, bool]:
        existing = self.registry.find_equivalent("Build Check", "Check whether a project builds correctly")
        if existing:
            return existing, None, False
        skill = SkillSpec(
            id="project-build-check",
            name="Project Build Check",
            version="1.0.0",
            description="Inspect a project, discover its build command, execute it safely, and verify real output.",
            category="coding",
            inputs={"project_root": {"type": "string", "required": True}},
            outputs={"build_passed": {"type": "boolean"}, "evidence": {"type": "array"}},
            required_capabilities=["filesystem.read", "terminal.execute", "coding.build_check", "coding.verify"],
            required_tools=["filesystem", "terminal"],
            required_permissions=PermissionLevel.L1,
            steps=[
                SkillStep(id="inspect", action="inspect_project", capability="filesystem.read", tool="filesystem"),
                SkillStep(id="discover", action="discover_build_command", capability="coding.build_check", depends_on=["inspect"]),
                SkillStep(id="build", action="run_build", capability="terminal.execute", tool="terminal", depends_on=["discover"]),
                SkillStep(id="verify", action="verify_exit_code", capability="coding.verify", depends_on=["build"]),
            ],
            verification=SkillVerification(checks=["build command discovered", "exit code is zero", "command evidence stored"]),
            created_by=created_by,
            status=SkillStatus.TESTING,
            success_rate=0.5,
        )
        evaluation = await self.sandbox.test(skill)
        skill = self.evaluator.apply(skill, evaluation)
        self.registry.register(
            skill,
            instructions="Execute only through the registered Coding Worker. Require a discovered build command, bounded terminal execution, exit-code verification, and evidence.",
            changelog="# Changelog\n\n## 1.0.0\n- Initial sandbox-tested build verification procedure.",
        )
        return skill, evaluation, True
