from __future__ import annotations

import time
from datetime import datetime, timezone

from app.execution.action_engine import ActionEngine
from app.schemas.tasks import Task, TaskDomain, TaskProfile

from .registry import SkillRegistry
from .schemas import SkillStatus


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, action_engine: ActionEngine):
        self.registry = registry
        self.action_engine = action_engine

    async def execute(self, skill_id: str, task: Task, emit):
        skill = self.registry.get(skill_id)
        if not skill or skill.status not in {SkillStatus.APPROVED, SkillStatus.ACTIVE}:
            raise RuntimeError(f"Skill is not active: {skill_id}")
        if skill_id != "project-build-check":
            raise RuntimeError("No production executor exists for this declarative skill")
        started = time.perf_counter()
        result = await self.action_engine.execute(
            task,
            TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="inspect_project_build", needs={"tools"}),
            emit,
        )
        elapsed = (time.perf_counter() - started) * 1000
        passed = bool(result.structured_data.get("verification", {}).get("passed"))
        skill.metrics.executions += 1
        skill.metrics.successes += int(passed)
        skill.metrics.failures += int(not passed)
        skill.metrics.verification_score = 1.0 if passed else 0.0
        skill.metrics.average_runtime_ms = (
            (skill.metrics.average_runtime_ms * (skill.metrics.executions - 1) + elapsed) / skill.metrics.executions
        )
        skill.success_rate = skill.metrics.successes / skill.metrics.executions
        skill.last_used = datetime.now(timezone.utc)
        self.registry.save(skill)
        return result
